"""Company-scoped inspection of an already analyzed Meta video asset."""

import math
from uuid import UUID

from fastapi import HTTPException

from app import meta_library_repository as library
from app.company_authorization import authorize
from app.video_repository import read_analysis


def authorized_asset(db, user, company_id: UUID, creative_ref: UUID):
    company = authorize(db, user, company_id)
    rows = db.execute("""SELECT asset.id, asset.video_id, asset.analysis_state,
               asset.analysis_version, asset.external_id, asset.platform,
               asset.connection_id, account.external_id AS account_external_id,
               ad.label AS ad_label, connection.status, connection.expires_at,
               connection.token_ciphertext
        FROM company_ad_assignments assignment
        JOIN meta_library_items ad ON ad.id=assignment.ad_item_id
          AND ad.connection_id=assignment.connection_id
          AND ad.account_id=assignment.account_id AND ad.content_type='ad'
        JOIN meta_ad_assets edge ON edge.ad_item_id=ad.id
        JOIN meta_library_items asset ON asset.id=edge.video_item_id
          AND asset.connection_id=ad.connection_id AND asset.content_type='video'
        JOIN meta_accounts account ON account.id=asset.account_id
          AND account.connection_id=asset.connection_id
        JOIN meta_connections connection ON connection.id=asset.connection_id
        WHERE assignment.company_id=%s AND asset.id=%s
          AND assignment.connection_id=%s""",
        (company_id, creative_ref, company['connection_id'])).fetchall()
    if not rows:
        raise HTTPException(404, 'Creative was not found.')
    # A video reused by multiple ads has no unique ad label, but its asset
    # identity and company authorization remain unambiguous.
    asset = rows[0]
    if any(row['video_id'] != asset['video_id'] or row['connection_id'] != asset['connection_id'] for row in rows):
        raise HTTPException(409, 'Creative mapping is ambiguous.')
    label = asset['ad_label'] if len(rows) == 1 and isinstance(asset['ad_label'], str) and asset['ad_label'].strip() else None
    return asset, label


def _seconds(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def detail(db, user, company_id, creative_ref):
    asset, label = authorized_asset(db, user, company_id, creative_ref)
    if asset['analysis_state'] != 'completed' or asset['video_id'] is None:
        raise HTTPException(404, 'Stored creative analysis was not found.')
    analysis = read_analysis(db, asset['video_id'], connection_id=asset['connection_id'])
    if analysis is None:
        raise HTTPException(404, 'Stored creative analysis was not found.')
    metadata = analysis.get('metadata') or {}
    video = metadata.get('video') or {}
    duration = _seconds(metadata.get('duration_seconds'))
    if duration == 0:
        duration = None
    scenes = []
    for row in analysis.get('scenes') or []:
        start, end = _seconds(row.get('start_seconds')), _seconds(row.get('end_seconds'))
        if start is not None and end is not None and end >= start:
            scenes.append({'scene_number': row.get('scene_number'), 'start_seconds': start, 'end_seconds': end})
    transcript = []
    for row in (analysis.get('audio') or {}).get('segments') or []:
        start, end = _seconds(row.get('start')), _seconds(row.get('end'))
        if start is not None and end is not None and end >= start and isinstance(row.get('text'), str):
            transcript.append({'start_seconds': start, 'end_seconds': end, 'text': row['text']})
    ocr = []
    for row in analysis.get('on_screen_text') or []:
        start = _seconds(row.get('appearance_timestamp_seconds'))
        end = _seconds(row.get('disappearance_timestamp_seconds'))
        if start is not None and end is not None and end >= start and isinstance(row.get('text'), str):
            # OCR coordinates belong to the normalized processing copy; the
            # provider source may have different dimensions. Never overlay.
            ocr.append({'appearance_seconds': start, 'disappearance_seconds': end, 'text': row['text']})
    connected = asset['status'] == 'connected' and asset['expires_at'] > library.now()
    return {'creative_ref': str(creative_ref), 'label': label or 'Analyzed creative',
            'duration_seconds': duration,
            'resolution': {'width': video.get('resolution', {}).get('width'),
                           'height': video.get('resolution', {}).get('height')},
            'scenes': scenes, 'transcript': transcript, 'ocr': ocr,
            'media': {'state': 'resolution_required' if connected else 'unavailable'}}
