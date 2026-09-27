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
            i.content_type, i.published_at, i.analysis_state,
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
    return {'items': items, 'next_offset': offset + limit if more else None}
