"""Authorized stored evidence and bounded same-origin Meta media playback."""

import re
import time
from uuid import UUID
from urllib.parse import urljoin

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from app import meta, meta_library_repository as library
from app.auth import bearer_token, get_token_verifier, require_authenticated_user
from app.creative_analysis import authorized_asset, detail
from app.meta_media import MAX_BYTES, MediaUnavailable, media_url, validate_url

router = APIRouter(prefix='/api/companies/{company_id}/creatives/{creative_ref}', tags=['creative analysis'])
PRIVATE = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}


def _asset(user, company_id, creative_ref):
    try:
        with library.database() as db, db.transaction():
            asset, _ = authorized_asset(db, user, company_id, creative_ref)
        return asset
    except (psycopg.Error, ValueError):
        raise HTTPException(503, 'Creative media is unavailable.') from None


@router.get('/analysis')
def analysis(company_id: UUID, creative_ref: UUID, user=Depends(require_authenticated_user)):
    try:
        with library.database() as db, db.transaction():
            result = detail(db, user, company_id, creative_ref)
        return JSONResponse(jsonable_encoder(result), headers=PRIVATE)
    except (psycopg.Error, ValueError):
        raise HTTPException(503, 'Creative analysis is unavailable.') from None


@router.post('/media-access')
def media_access(request: Request, company_id: UUID, creative_ref: UUID,
                 user=Depends(require_authenticated_user)):
    """Give the native video element a path-scoped, HttpOnly browser credential.

    It is the already-verified Supabase JWT, not a provider token. The media
    route verifies it anew and re-authorizes the asset on every range request.
    """
    asset = _asset(user, company_id, creative_ref)
    if asset['status'] != 'connected' or asset['expires_at'] <= library.now():
        raise HTTPException(503, 'Video currently unavailable.')
    response = JSONResponse({'ready': True}, headers=PRIVATE)
    response.set_cookie('cm_creative_media', bearer_token(request), max_age=900,
                        path=f'/api/companies/{company_id}/creatives/{creative_ref}/media',
                        httponly=True, secure=request.url.hostname not in ('localhost', '127.0.0.1'),
                        samesite='strict')
    return response


def _open_media(url, range_header):
    client = httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False, trust_env=False)
    try:
        for _ in range(4):
            validate_url(url)
            headers = {'Accept-Encoding': 'identity'}
            if range_header:
                headers['Range'] = range_header
            response = client.send(client.build_request('GET', url, headers=headers), stream=True)
            if response.status_code in (301, 302, 303, 307, 308):
                next_url = urljoin(url, response.headers.get('location', ''))
                response.close()
                url = next_url
                continue
            if response.status_code in (403, 404, 410):
                response.close()
                raise MediaUnavailable('Meta media is currently unavailable.')
            if response.status_code not in (200, 206) or range_header and response.status_code != 206:
                response.close()
                raise MediaUnavailable('Meta did not return seekable video.')
            content_type = response.headers.get('content-type', '').split(';')[0].lower()
            if (content_type not in ('video/mp4', 'video/quicktime', 'video/webm', 'application/octet-stream')
                    or response.headers.get('content-encoding', 'identity').lower() != 'identity'):
                response.close()
                raise MediaUnavailable('Meta returned unsupported video data.')
            length = response.headers.get('content-length')
            if not length or not length.isdecimal() or int(length) < 1 or int(length) > MAX_BYTES:
                response.close()
                raise MediaUnavailable('Video exceeds media limits.')
            output = {'Content-Type': content_type, 'Content-Length': length,
                      'Accept-Ranges': 'bytes', **PRIVATE}
            if response.status_code == 206:
                matched = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('content-range', ''))
                requested = re.fullmatch(r'bytes=(\d+)-(\d*)', range_header or '')
                if (not matched or int(matched[3]) > MAX_BYTES or int(matched[2]) < int(matched[1])
                        or int(length) != int(matched[2]) - int(matched[1]) + 1
                        or requested and (int(matched[1]) != int(requested[1])
                                          or requested[2] and int(matched[2]) > int(requested[2]))):
                    response.close()
                    raise MediaUnavailable('Meta returned an invalid byte range.')
                output['Content-Range'] = response.headers['content-range']
            return client, response, output
        raise MediaUnavailable('Too many media redirects.')
    except Exception:
        client.close()
        raise


@router.get('/media')
def media(request: Request, company_id: UUID, creative_ref: UUID):
    token = request.cookies.get('cm_creative_media')
    if not token:
        raise HTTPException(401, 'Media access expired.')
    user = get_token_verifier().verify(token)
    asset = _asset(user, company_id, creative_ref)
    if asset['status'] != 'connected' or asset['expires_at'] <= library.now():
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
