"""Company-scoped stored evidence and same-origin playback for library content."""

import math
import re
import time
from uuid import UUID

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse, Response

from app import company_ownership_repository as ownership, meta, meta_library_repository as library
from app.auth import bearer_token, get_token_verifier, require_authenticated_user
from app.company_authorization import authorize
from app.creative_analysis_routes import PRIVATE, _open_media
from app.meta_media import MAX_BYTES, MediaUnavailable, media_url, preview_url, preview_bytes

router = APIRouter(prefix='/api/companies/{company_id}/content/{item_id}', tags=['content analysis'])
METRICS = ('view_count', 'like_count', 'comment_count', 'share_count', 'reach', 'impressions')


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def _item(db, user, company_id, item_id):
    company = authorize(db, user, company_id)
    connection = company['connection_id']
    try:
        item = ownership._selected(db, connection, company_id, item_id)
    except ownership.OwnershipNotFound:
        raise HTTPException(404, 'Stored content analysis was not found.') from None
    if (item['content_type'] == 'ad' or item['analysis_state'] != 'completed'
            or item['analysis_version'] != library.ANALYSIS_VERSION or not item['video_id']):
        raise HTTPException(404, 'Stored content analysis was not found.')
    video = db.execute('SELECT id FROM videos WHERE id=%s AND meta_connection_id=%s AND analysis_version=%s',
                       (item['video_id'], connection, item['analysis_version'])).fetchone()
    if not video:
        raise HTTPException(404, 'Stored content analysis was not found.')
    return item, connection


def detail(db, user, company_id, item_id):
    item, connection = _item(db, user, company_id, item_id)
    stored = ownership.analysis(db, connection, company_id, item_id)
    if not stored:
        raise HTTPException(404, 'Stored content analysis was not found.')
    video = stored['video']
    title = ('Instagram reel' if item['content_type'] == 'reel' else
             'Instagram video' if item['platform'] == 'instagram' else 'Facebook video')
    def ranges(rows, start_key, end_key, fields):
        result = []
        for row in rows:
            start, end = _number(row.get(start_key)), _number(row.get(end_key))
            if start is not None and end is not None and end >= start:
                result.append({start_key: start, end_key: end,
                               **{key: float(row[key]) if key == 'confidence' and row.get(key) is not None
                                  else row.get(key) for key in fields}})
        return result
    snapshots = ownership.performance(db, connection, company_id, item_id)
    performance = {}
    for record in snapshots:
        if record['item_id'] != item_id or record['attribution'] != 'organic':
            continue
        snapshot = record['snapshot'] or {}
        if not isinstance(snapshot, dict) or snapshot.get('performance_source') != item['platform']:
            continue
        metrics = snapshot.get('performance_metrics') or {}
        if isinstance(metrics, dict):
            performance = {key: metrics[key] for key in METRICS
                           if type(metrics.get(key)) is int and metrics[key] >= 0}
    state = db.execute('''SELECT c.status,c.expires_at FROM meta_connections c
        WHERE c.id=%s''', (connection,)).fetchone()
    connected = bool(state and state['status'] == 'connected' and state['expires_at'] > library.now())
    return {'item': {'id': str(item_id), 'platform': item['platform'],
                     'content_type': item['content_type'], 'published_at': item['published_at'],
                     'display_title': title, 'analysis_state': item['analysis_state']},
            'duration_seconds': _number(video['duration_seconds']),
            'resolution': {'width': video['width'], 'height': video['height']},
            'scenes': ranges(stored['scenes'], 'start_seconds', 'end_seconds', ('scene_number',)),
            'transcript': ranges(stored['transcript_segments'], 'start_seconds', 'end_seconds', ('text',)),
            'ocr': [{'appearance_seconds': row['appearance_timestamp_seconds'],
                     'disappearance_seconds': row['disappearance_timestamp_seconds'],
                     'text': row['text'], 'confidence': float(row['confidence'])}
                    for row in stored['on_screen_text']],
            'motion': ranges(stored['motion_events'], 'start_seconds', 'end_seconds', ('type', 'confidence')),
            'performance': performance,
            'media': {'state': 'resolution_required' if connected else 'unavailable'}}


def _asset(user, company_id, item_id):
    try:
        with library.database() as db, db.transaction():
            item, connection = _item(db, user, company_id, item_id)
            return db.execute('''SELECT i.external_id,i.platform,a.external_id AS account_external_id,
                c.status,c.expires_at,c.token_ciphertext,c.id AS connection_id
                FROM meta_library_items i JOIN meta_accounts a ON a.id=i.account_id AND a.connection_id=i.connection_id
                JOIN meta_connections c ON c.id=i.connection_id
                WHERE i.id=%s AND i.connection_id=%s''', (item['id'], connection)).fetchone()
    except (psycopg.Error, ValueError):
        raise HTTPException(503, 'Video currently unavailable.') from None


@router.get('/preview')
def preview(request: Request, company_id: UUID, item_id: UUID,
            verifier=Depends(get_token_verifier)):
    token = request.cookies.get('cm_content_preview')
    if not token:
        raise HTTPException(401, 'Preview access expired.')
    user = verifier.verify(token)
    try:
        with library.database() as db, db.transaction():
            company = authorize(db, user, company_id)
            connection = company['connection_id']
            try:
                item = ownership._selected(db, connection, company_id, item_id)
            except ownership.OwnershipNotFound:
                raise HTTPException(404, 'Content was not found.') from None
            if item['content_type'] == 'ad' or item['platform'] not in ('instagram','facebook'):
                raise HTTPException(404, 'Content was not found.')
            asset = db.execute('''SELECT i.external_id,i.platform,a.external_id AS account_external_id,
                c.status,c.expires_at,c.token_ciphertext,c.id AS connection_id
                FROM meta_library_items i JOIN meta_accounts a ON a.id=i.account_id
                JOIN meta_connections c ON c.id=i.connection_id
                WHERE i.id=%s AND i.connection_id=%s
                  AND a.platform IN ('facebook','instagram')''', (item_id, connection)).fetchone()
    except (psycopg.Error, ValueError):
        raise HTTPException(503, 'Preview unavailable.') from None
    if not asset or asset['status'] != 'connected' or asset['expires_at'] <= library.now():
        raise HTTPException(404, 'Preview unavailable.')
    try:
        data, content_type = preview_bytes(preview_url(library.connection_client(asset), asset))
    except (MediaUnavailable, meta.MetaError, httpx.HTTPError, ValueError):
        raise HTTPException(404, 'Preview unavailable.') from None
    return Response(data, media_type=content_type,
                    headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/analysis')
def analysis(company_id: UUID, item_id: UUID, user=Depends(require_authenticated_user)):
    try:
        with library.database() as db, db.transaction():
            result = detail(db, user, company_id, item_id)
        return JSONResponse(jsonable_encoder(result), headers=PRIVATE)
    except (psycopg.Error, ValueError):
        raise HTTPException(503, 'Content analysis is unavailable.') from None


@router.post('/media-access')
def media_access(request: Request, company_id: UUID, item_id: UUID,
                 user=Depends(require_authenticated_user)):
    asset = _asset(user, company_id, item_id)
    if not asset or asset['status'] != 'connected' or asset['expires_at'] <= library.now():
        raise HTTPException(503, 'Video currently unavailable.')
    response = JSONResponse({'ready': True}, headers=PRIVATE)
    response.set_cookie('cm_content_media', bearer_token(request), max_age=900,
                        path=f'/api/companies/{company_id}/content/{item_id}/media',
                        httponly=True, secure=request.url.hostname not in ('localhost', '127.0.0.1'),
                        samesite='strict')
    return response


@router.get('/media')
def media(request: Request, company_id: UUID, item_id: UUID):
    token = request.cookies.get('cm_content_media')
    if not token:
        raise HTTPException(401, 'Media access expired.')
    user = get_token_verifier().verify(token)
    asset = _asset(user, company_id, item_id)
    if not asset or asset['status'] != 'connected' or asset['expires_at'] <= library.now():
        raise HTTPException(503, 'Video currently unavailable.')
    range_header = request.headers.get('range')
    if range_header and not re.fullmatch(r'bytes=\d+-\d*', range_header):
        raise HTTPException(416, 'Unsupported byte range.')
    try:
        url = media_url(library.connection_client(asset), asset)
        client, upstream, headers = _open_media(url, range_header)
    except (MediaUnavailable, meta.MetaError, httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Video currently unavailable.') from None
    def chunks():
        size, started = 0, time.monotonic()
        try:
            for chunk in upstream.iter_raw(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() - started > 300:
                    break
                yield chunk
        finally:
            upstream.close()
            client.close()
    return StreamingResponse(chunks(), status_code=upstream.status_code, headers=headers)
