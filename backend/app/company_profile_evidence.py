"""Bounded stored evidence; no provider reads, media processing or model calls."""

import hashlib
import json

from fastapi.encoders import jsonable_encoder
from psycopg import sql

from app import company_profile_types as p
from app import company_profile_repository as repo


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
    accounts = list(access.account_ids)
    total = db.execute('''SELECT count(*) AS total,count(*) FILTER (WHERE analysis_state='completed') AS analyzed
        FROM meta_library_items WHERE account_id=ANY(%s::uuid[]) AND platform=%s''',
        (accounts, scope)).fetchone()
    rows = db.execute('''SELECT id,account_id,connection_id,platform,content_type,
        left(label,%s) AS label,published_at,analysis_state,analysis_version,video_id
        FROM meta_library_items WHERE account_id=ANY(%s::uuid[]) AND platform=%s
        ORDER BY published_at DESC NULLS LAST,id LIMIT %s''',
        (p.MAX_TEXT_CHARS, accounts, scope, p.MAX_ITEMS)).fetchall()
    if scope == 'meta_ads':
        # Ad creative assets can live under a different platform but must be assigned to this company.
        assets = db.execute('''SELECT DISTINCT i.id,i.account_id,i.connection_id,i.platform,i.content_type,
            left(i.label,%s) AS label,i.published_at,i.analysis_state,i.analysis_version,i.video_id
            FROM meta_ad_assets a JOIN meta_library_items i ON i.id=a.video_item_id
            WHERE a.ad_item_id=ANY(%s::uuid[]) AND i.account_id=ANY(%s::uuid[])
            ORDER BY i.published_at DESC NULLS LAST,i.id LIMIT %s''',
            (p.MAX_TEXT_CHARS, [r['id'] for r in rows], accounts, p.MAX_ITEMS)).fetchall()
        source_rows = assets
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
                (p.MAX_TRANSCRIPT_CHARS, row['video_id'], row['connection_id'])).fetchone()
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
    source_ids = [r['id'] for r in rows + source_rows]
    metrics = db.execute('''SELECT perf.item_id,perf.snapshot,perf.fetched_at,i.content_type,
        (SELECT count(*) FROM meta_ad_assets a WHERE a.ad_item_id=i.id) AS asset_count
        FROM meta_library_performance perf JOIN meta_library_items i ON i.id=perf.item_id
        WHERE i.account_id=ANY(%s::uuid[]) AND (i.id=ANY(%s::uuid[]) OR i.id IN (
            SELECT ad_item_id FROM meta_ad_assets WHERE video_item_id=ANY(%s::uuid[])))
        AND octet_length(perf.snapshot::text)<=%s ORDER BY i.id LIMIT %s''',
        (accounts, source_ids, source_ids, p.MAX_INPUT_BYTES, p.MAX_PERFORMANCES)).fetchall()
    performances = []
    for metric in metrics:
        metric['ref'] = 'performance:' + str(metric['item_id'])
        metric['attribution'] = ('shared_ad' if metric['asset_count'] > 1 else 'ad') if metric['content_type'] == 'ad' else 'organic'
        performances.append(metric)
    links = db.execute('''SELECT a.ad_item_id,a.video_item_id FROM meta_ad_assets a
        JOIN meta_library_items ad ON ad.id=a.ad_item_id JOIN meta_library_items v ON v.id=a.video_item_id
        WHERE ad.account_id=ANY(%s::uuid[]) AND v.account_id=ANY(%s::uuid[])
        AND v.id=ANY(%s::uuid[]) AND (%s<>'meta_ads' OR ad.id=ANY(%s::uuid[]))
        ORDER BY ad.id,v.id LIMIT %s''',
        (accounts, accounts, [r['id'] for r in source_rows], scope, [r['id'] for r in rows], p.MAX_RELATIONSHIPS)).fetchall()
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
