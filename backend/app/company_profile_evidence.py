"""Bounded stored evidence; no provider reads, media processing or model calls."""

import hashlib
import json

from fastapi.encoders import jsonable_encoder
from psycopg import sql

from app import company_profile_types as p
from app import company_profile_repository as repo
from app import company_ownership_repository as ownership


def encoded(value):
    return json.dumps(jsonable_encoder(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def semantic(value):
    """Retrieval time remains provenance but does not change the effective evidence."""
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k != 'fetched_at'}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def fingerprint(bundle, model):
    payload = semantic(bundle['payload'])
    dependencies = {scope: {'revision_id': dep['revision_id'], 'suppressed': dep['suppressed']}
                    for scope, dep in bundle['dependencies'].items()}
    if payload['scope'] == 'shared':
        # Input event counters and transient freshness are publication fences, not new intelligence.
        payload['coverage']['dependencies'] = dependencies
    data = {'evidence': payload, 'assignment': bundle['assignment_version'],
            'dependencies': dependencies, 'model': model,
            'generator': p.GENERATOR_VERSION, 'schema': p.SCHEMA_VERSION}
    return hashlib.sha256(encoded(data).encode()).hexdigest()


def children(db, video_id, table, order, limit, columns):
    return db.execute(sql.SQL('SELECT {} FROM {} WHERE video_id=%s ORDER BY {} LIMIT %s').format(
        sql.SQL(columns), sql.Identifier(table), sql.Identifier(order)), (video_id, limit)).fetchall()


def platform(db, company_id, scope, access):
    # Reuse 006's exact item-level boundary. Account membership alone never
    # authorizes an ad, its performance, or traversal to a sibling ad.
    ownership.require_active_company(db, access.connection_id, company_id)
    params = dict(connection_id=access.connection_id, company_id=company_id,
                  scope=scope, text_limit=p.MAX_TEXT_CHARS, item_limit=p.MAX_ITEMS,
                  byte_limit=p.MAX_INPUT_BYTES, performance_limit=p.MAX_PERFORMANCES,
                  relationship_limit=p.MAX_RELATIONSHIPS)
    scoped = ownership.COMPANY_SCOPE_SQL + """,
    candidates AS (
        SELECT i.* FROM valid_items i JOIN accessible_items visible ON visible.id=i.id
        WHERE (%(scope)s='meta_ads' AND i.content_type='ad')
        OR (%(scope)s<>'meta_ads' AND i.content_type<>'ad' AND i.platform=%(scope)s)
    )
    """
    total = db.execute(scoped + """SELECT count(*) AS total,
        count(*) FILTER (WHERE analysis_state='completed') AS analyzed FROM candidates""", params).fetchone()
    # V2 discovery can overwrite a shared creative's label with another ad's
    # name. Match 006's sanitized content projection, including organic views.
    projection = """id,connection_id,platform,content_type,
        CASE WHEN content_type='ad' THEN left(label,%(text_limit)s) ELSE NULL END AS label,
        published_at,analysis_state,analysis_version,video_id"""
    rows = db.execute(scoped + 'SELECT ' + projection + """ FROM candidates
        ORDER BY published_at DESC NULLS LAST,id LIMIT %(item_limit)s""", params).fetchall()
    params['selected_ids'] = [r['id'] for r in rows]
    if scope == 'meta_ads':
        assets = ownership.COMPANY_SCOPE_SQL + """,
        assets AS (
            SELECT DISTINCT asset.* FROM direct_items ad
            JOIN meta_ad_assets edge ON edge.ad_item_id=ad.id
            JOIN valid_items asset ON asset.id=edge.video_item_id
            WHERE ad.content_type='ad' AND ad.id=ANY(%(selected_ids)s::uuid[])
            AND asset.content_type<>'ad'
        )
        """
        source_rows = db.execute(assets + 'SELECT ' + projection + """ FROM assets
            ORDER BY published_at DESC NULLS LAST,id LIMIT %(item_limit)s""", params).fetchall()
    else:
        source_rows = rows
    items, seen_videos = [], set()
    for row in source_rows:
        item = {k: row[k] for k in ('id','platform','content_type','label','published_at','analysis_state','analysis_version')}
        item['ref'] = 'item:' + str(row['id'])
        item['analysis'] = None
        if row['video_id'] and row['analysis_state'] == 'completed' and row['video_id'] not in seen_videos:
            video = db.execute('''SELECT id,duration_seconds,width,height,fps,
                left(transcript_text,%s) AS transcript,analysis_version FROM videos
                WHERE id=%s AND meta_connection_id=%s''',
                (p.MAX_TRANSCRIPT_CHARS, row['video_id'], access.connection_id)).fetchone()
            if video:
                seen_videos.add(row['video_id'])
                video['scenes'] = children(db, row['video_id'], 'scenes', 'scene_number', p.MAX_SCENES,
                                          'scene_number,start_seconds,end_seconds,duration_seconds')
                video['on_screen_text'] = children(db, row['video_id'], 'on_screen_text', 'detection_index', p.MAX_OCR,
                    f'left(text,{p.MAX_TEXT_CHARS}) AS text,confidence,appearance_timestamp_seconds,disappearance_timestamp_seconds')
                video['motion_events'] = children(db, row['video_id'], 'motion_events', 'event_index', p.MAX_MOTION,
                    f'left(type,{p.MAX_TEXT_CHARS}) AS type,confidence,start_seconds,end_seconds')
                item['analysis'] = video
        items.append(item)
    params['source_ids'] = [r['id'] for r in rows + source_rows]
    params['asset_ids'] = [r['id'] for r in source_rows]
    metrics = db.execute(ownership.COMPANY_SCOPE_SQL + '''SELECT perf.item_id,perf.snapshot,perf.fetched_at,i.content_type,
        (SELECT count(*) FROM meta_ad_assets edge JOIN valid_items asset ON asset.id=edge.video_item_id
         WHERE edge.ad_item_id=i.id AND asset.content_type<>'ad') AS asset_count
        FROM meta_library_performance perf JOIN direct_items i ON i.id=perf.item_id
        WHERE (i.id=ANY(%(source_ids)s::uuid[]) OR (i.content_type='ad' AND EXISTS (
            SELECT 1 FROM meta_ad_assets edge WHERE edge.ad_item_id=i.id
            AND edge.video_item_id=ANY(%(asset_ids)s::uuid[]))))
        AND octet_length(perf.snapshot::text)<=%(byte_limit)s
        ORDER BY i.id LIMIT %(performance_limit)s''', params).fetchall()
    performances = []
    for metric in metrics:
        metric['ref'] = 'performance:' + str(metric['item_id'])
        metric['attribution'] = ('shared_ad' if metric['asset_count'] > 1 else 'ad') if metric['content_type'] == 'ad' else 'organic'
        performances.append(metric)
    links = db.execute(ownership.COMPANY_SCOPE_SQL + '''SELECT edge.ad_item_id,edge.video_item_id
        FROM meta_ad_assets edge JOIN direct_items ad ON ad.id=edge.ad_item_id
        JOIN valid_items asset ON asset.id=edge.video_item_id
        WHERE ad.content_type='ad' AND asset.content_type<>'ad'
        AND asset.id=ANY(%(asset_ids)s::uuid[])
        AND (%(scope)s<>'meta_ads' OR ad.id=ANY(%(selected_ids)s::uuid[]))
        ORDER BY ad.id,asset.id LIMIT %(relationship_limit)s''', params).fetchall()
    return {'scope': scope, 'items': items, 'performances': performances, 'relationships': links,
            'platform_profiles': [], 'evidence_registry': {}, 'coverage': {
                'available_items': total['total'], 'completed_items': total['analyzed'],
                'selected_items': len(items), 'included_items': len(items),
                'included_performances': len(performances), 'bounded_sample': True,
                'selection': 'most recent publication, null dates last, UUID tie-breaker',
                'analysis_policy': 'stored completed analysis only; deferred history is not processed',
                'limitations': ['Metrics may be missing or oversized; child records and text are capped.'],
            }}


def shared(db, company_id):
    profiles, dependencies, registry = [], {}, {}
    for scope in p.PLATFORMS:
        row = repo.profile(db, company_id, scope)
        state = repo.freshness(row)
        rev = None
        if row and row['current_revision_id'] and not row['suppressed']:
            rev = db.execute('SELECT * FROM company_profile_revisions WHERE profile_id=%s AND id=%s',
                             (row['id'], row['current_revision_id'])).fetchone()
        dependencies[scope] = {'revision_id': str(rev['id']) if rev else None,
                               'input_revision': row['input_revision'] if row else 0,
                               'freshness': state, 'suppressed': row['suppressed'] if row else False}
        if rev:
            profile_refs = rev['evidence_manifest']['references']
            profiles.append({'ref': 'profile:' + str(rev['id']), 'scope': scope,
                             'document': rev['document'], 'evidence_refs': sorted(profile_refs)})
            for ref, metadata in profile_refs.items():
                if ref in registry and semantic(registry[ref]) != semantic(metadata):
                    # One source is still one source, even when cached platform views differ.
                    registry[ref] = {**registry[ref], 'conflicting_versions': True}
                else:
                    registry[ref] = metadata
    return {'scope': 'shared', 'items': [], 'performances': [], 'relationships': [],
            'platform_profiles': profiles, 'evidence_registry': registry,
            'coverage': {'available_platforms': len(profiles), 'dependencies': dependencies,
                         'bounded_sample': True, 'limitations': ['Shared evidence is derived from platform revisions.']}}, dependencies


def performance_reference(metric):
    snapshot = metric['snapshot']
    values = snapshot.get('performance_metrics', {})
    ad = values.get('meta_ads') or {}
    context = {key: ad.get(key) for key in (
        'currency', 'account_currency', 'date_start', 'date_stop', 'action_report_time',
        'action_attribution_windows', 'attribution_windows', 'metric_definitions')}
    context.update({'source': snapshot.get('performance_source'),
                    'attribution': metric['attribution']})
    # Only explicitly known scalar measurements can support an automated comparison gate.
    known = sorted(key for key, value in {**values, **ad}.items()
                   if isinstance(value, (int, float)) and not isinstance(value, bool))
    return {'kind': 'measured_performance', 'item_id': str(metric['item_id']),
            'attribution': metric['attribution'], 'context': context, 'known_metrics': known,
            'snapshot_hash': hashlib.sha256(encoded(semantic(snapshot)).encode()).hexdigest(),
            'fetched_at': metric['fetched_at']}


def references(payload):
    refs = dict(payload.get('evidence_registry', {}))
    for item in payload['items']:
        analysis = item['analysis']
        refs[item['ref']] = {'kind': 'content', 'item_id': str(item['id']),
                             'analysis_version': item['analysis_version'],
                             'analysis_hash': hashlib.sha256(encoded(analysis).encode()).hexdigest() if analysis else None}
    for metric in payload['performances']:
        refs[metric['ref']] = performance_reference(metric)
    for profile in payload['platform_profiles']:
        refs[profile['ref']] = {'kind': 'profile', 'scope': profile['scope']}
    return refs


def bound(payload, overhead):
    """Trim complete units, retaining relationships only between included units."""
    payload = jsonable_encoder(payload)
    def update_coverage():
        payload['coverage']['included_items'] = len(payload['items'])
        payload['coverage']['included_performances'] = len(payload['performances'])
        payload['coverage']['included_platforms'] = len(payload['platform_profiles'])
        included_refs = {ref for profile in payload['platform_profiles'] for ref in profile['evidence_refs']}
        payload['evidence_registry'] = {ref: value for ref, value in payload.get('evidence_registry', {}).items()
                                        if ref in included_refs}
    update_coverage()
    while len(encoded(payload).encode()) + overhead > p.MAX_INPUT_BYTES:
        candidates = [key for key in ('items', 'performances', 'platform_profiles') if payload[key]]
        if not candidates:
            raise ValueError('Profile input overhead exceeds limit.')
        # Deterministic: retain each list's leading evidence; drop its largest tail unit first.
        key = max(candidates, key=lambda name: len(encoded(payload[name][-1]).encode()))
        removed = payload[key].pop()
        if key == 'items':
            payload['relationships'] = [link for link in payload['relationships']
                                         if link['video_item_id'] != removed['id']]
        payload['coverage']['input_truncated'] = True
        update_coverage()
    return payload


def assemble(db, company_id, scope, adapter, *, overhead=0):
    access = adapter.evidence_access(db, company_id)
    dependencies = {}
    if scope == 'shared':
        payload, dependencies = shared(db, company_id)
    else:
        payload = platform(db, company_id, scope, access)
    payload = bound(payload, overhead + p.INPUT_RESERVE_BYTES)
    return {'payload': payload, 'assignment_version': str(access.version),
            'dependencies': dependencies,
            'manifest': {'references': references(payload), 'coverage': payload['coverage'],
                         'performances': payload['performances']}}
