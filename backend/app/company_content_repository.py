"""Bounded, content-only cards over the V3 ownership scope."""

from app import company_ownership_repository as ownership
from app import meta_library_repository as library


@ownership._transaction
def list_content(db, connection_id, company_id, *, analyzed_only=False,
                 platform=None, content_type=None, search=None, published_from=None,
                 published_to=None, limit=20, offset=0, order='desc'):
    ownership.require_active_company(db, connection_id, company_id)
    # Project safe fields BEFORE search/pagination. Organic/creative labels may
    # contain another ad's metadata (even for directly owned organic items).
    # Never join performance or project raw errors, tokens, URLs or provider IDs.
    direction = 'ASC' if order == 'asc' else 'DESC'
    params = dict(connection_id=connection_id, company_id=company_id,
                  version=library.ANALYSIS_VERSION, analyzed_only=analyzed_only,
                  platform=platform, content_type=content_type, search=search,
                  published_from=published_from, published_to=published_to,
                  limit=limit + 1, offset=offset)
    rows = db.execute(ownership.COMPANY_SCOPE_SQL + '''
    , cards AS (
        SELECT i.id AS library_item_id, v.id AS video_id, i.platform,
            i.content_type, i.published_at, i.analysis_state, i.analysis_stage,
            COALESCE(i.content_type<>'ad' AND i.analysis_state='completed'
                AND i.analysis_version=%(version)s
                AND v.analysis_version=i.analysis_version, false) AS analyzed,
            CASE WHEN i.content_type='ad' AND btrim(i.label)<>''
                AND position(i.external_id in i.label)=0
                AND position('://' in i.label)=0 AND position('www.' in i.label)=0
                THEN btrim(i.label)
                WHEN i.content_type='ad' THEN 'Meta ad'
                WHEN i.content_type='reel' THEN 'Instagram reel'
                ELSE CASE WHEN i.platform='instagram' THEN 'Instagram video'
                          ELSE 'Facebook video' END END AS display_title,
            v.duration_seconds, v.width, v.height
        FROM valid_items i JOIN accessible_items a ON a.id=i.id
        LEFT JOIN videos v ON v.id=i.video_id AND v.meta_connection_id=i.connection_id
    )
    SELECT * FROM cards
    WHERE (NOT %(analyzed_only)s OR analyzed)
        AND (%(platform)s::text IS NULL OR platform=%(platform)s)
        AND (%(content_type)s::text IS NULL OR content_type=%(content_type)s)
        AND (%(search)s::text IS NULL OR position(lower(%(search)s) in lower(display_title))>0)
        AND (%(published_from)s::timestamptz IS NULL OR published_at >= %(published_from)s)
        AND (%(published_to)s::timestamptz IS NULL OR published_at <= %(published_to)s)
    ''' + f'ORDER BY published_at {direction} NULLS LAST, library_item_id {direction} '
          'LIMIT %(limit)s OFFSET %(offset)s', params).fetchall()
    more = len(rows) > limit
    items = []
    for row in rows[:limit]:
        summary = {key: row.pop(key) for key in ('duration_seconds', 'width', 'height')}
        if summary['duration_seconds'] is not None:
            summary['duration_seconds'] = float(summary['duration_seconds'])
        items.append(dict(row, summary=summary))
    batch = db.execute('''SELECT r.id AS run_id,r.kind FROM meta_sync_runs r
        WHERE r.company_id=%s AND r.kind IN ('bootstrap','analysis')
          AND ((r.kind='analysis' AND EXISTS (
              SELECT 1 FROM meta_jobs j WHERE j.run_id=r.id
                  AND j.state IN ('queued','running','blocked')))
            OR (r.kind='bootstrap' AND EXISTS (
              SELECT 1 FROM meta_initial_analysis_targets t
              JOIN meta_library_items i ON i.id=t.item_id
              WHERE t.run_id=r.id AND i.analysis_state IN
                  ('queued','processing','discovered','deferred'))))
          AND (r.kind='analysis' OR EXISTS (
              SELECT 1 FROM meta_initial_analysis_batches b
              JOIN company_accounts ca ON ca.company_id=b.company_id AND ca.account_id=b.account_id
              WHERE b.run_id=r.id AND b.company_id=%s))
        ORDER BY r.created_at,r.id LIMIT 1''', (company_id, company_id)).fetchone()
    progress = None
    if batch:
        target_source = ('''meta_initial_analysis_targets t JOIN meta_library_items i ON i.id=t.item_id'''
                         if batch['kind'] == 'bootstrap' else
                         '''meta_jobs t JOIN meta_library_items i ON i.id=t.item_id''')
        targets = db.execute('''SELECT DISTINCT i.id,i.platform,i.content_type,i.published_at,
            i.analysis_state,i.analysis_stage,i.analysis_version,i.video_id
            FROM ''' + target_source + ''' WHERE t.run_id=%s''', (batch['run_id'],)).fetchall()
        completed = sum(bool(i['video_id'] and i['analysis_version'] == library.ANALYSIS_VERSION
                             and i['analysis_state'] == 'completed') for i in targets)
        failed = sum(i['analysis_state'] == 'failed' for i in targets)
        unavailable = sum(i['analysis_state'] in ('unavailable','unsupported') for i in targets)
        processing = sum(i['analysis_state'] == 'processing' for i in targets)
        queued = len(targets) - completed - failed - unavailable - processing
        if queued or processing:
            current = next((i for i in targets if i['analysis_state'] == 'processing'), None)
            progress = {'batch_id': batch['run_id'], 'total': len(targets),
                        'completed': completed, 'failed': failed, 'unavailable': unavailable,
                        'processing': processing, 'queued': queued,
                        'current_item_id': current['id'] if current else None,
                        'current_stage': current['analysis_stage'] if current else None,
                        'current_platform': current['platform'] if current else None,
                        'current_type': current['content_type'] if current else None,
                        'current_published_at': current['published_at'] if current else None}
    return {'items': items, 'next_offset': offset + limit if more else None,
            'analysis_progress': progress}
