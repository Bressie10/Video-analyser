"""Capture one consistent bounded input, call OpenAI outside transactions, then save."""
import hashlib
import json
import os
from uuid import UUID

import psycopg
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app import idea_repository as ideas
from app import meta_library_repository as library
from app.ad_metrics import normalize_ad_metrics
from app.idea_generation import EVIDENCE_SCHEMA_VERSION, RECOMMENDATION_VERSION, generate_idea
from app.idea_models import GeneratedIdea
from app.video_repository import read_analysis

MAX_EVIDENCE_BYTES = 1024 * 1024


def request_hash(body):
    request = body.model_dump(mode='json', exclude={'request_id'})
    request['target_platforms'] = sorted(request['target_platforms'])
    encoded = json.dumps(request, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def safe_snapshot(snapshot):
    """Allowlist the metric contract, never copy provider response dictionaries."""
    source = snapshot['performance_source']
    if source not in ('instagram', 'facebook', 'meta_ads'):
        raise HTTPException(409, 'Unsupported performance evidence.')
    metrics = snapshot['performance_metrics']
    safe = {key: metrics[key] for key in ('view_count', 'like_count', 'comment_count',
             'share_count', 'impressions', 'reach') if key in metrics}
    if any(value is not None and (type(value) is not int or not 0 <= value <= 9223372036854775807)
           for value in safe.values()):
        raise HTTPException(409, 'Invalid performance evidence.')
    if metrics.get('meta_ads') is not None:
        safe['meta_ads'] = normalize_ad_metrics(metrics['meta_ads'])
    return {'performance_source': source, 'performance_metrics': safe}


def publication(item):
    return {key: item[key] for key in ('platform', 'content_type', 'published_at')}


def capture_evidence(db, access, session, company_id, body):
    access.authorize(db, session, company_id, body.video_ids, write=True)
    captured_at = db.execute('SELECT transaction_timestamp() AS at').fetchone()['at']
    rows = db.execute('SELECT * FROM meta_library_items WHERE id=ANY(%s)',
                      (body.video_ids,)).fetchall()
    by_id = {row['id']: row for row in rows}
    if len(by_id) != len(body.video_ids):
        raise HTTPException(404, 'Source was not found.')
    videos, performance = [], {}
    for index, identity in enumerate(body.video_ids):
        item = by_id[identity]
        if (item['analysis_state'] != 'completed' or not item['video_id']
                or item['analysis_version'] != library.ANALYSIS_VERSION):
            raise HTTPException(409, 'Select videos with completed current-version analysis.')
        version = db.execute('SELECT analysis_version FROM videos WHERE id=%s',
                             (item['video_id'],)).fetchone()
        if not version or version['analysis_version'] != item['analysis_version']:
            raise HTTPException(409, 'Stored analysis version does not match the source.')
        analysis = read_analysis(db, item['video_id'], company_authorized=True)
        if analysis is None:
            raise HTTPException(409, 'Stored analysis is incomplete.')
        # Content only; mutable legacy metrics must not sneak into source analysis.
        analysis = {key: analysis[key] for key in
                    ('metadata', 'audio', 'scenes', 'on_screen_text', 'motion_events')}
        snapshots = library.public_performance(db, identity)
        owners = [s['item_id'] for s in snapshots]
        access.authorize(db, session, company_id, owners, write=True)
        for snapshot in snapshots:
            owner = snapshot['item_id']
            owner_item = db.execute('SELECT platform,content_type,published_at FROM meta_library_items WHERE id=%s',
                                    (owner,)).fetchone()
            performance[str(owner)] = {
                'library_item_id': owner, 'snapshot': safe_snapshot(snapshot['snapshot']),
                'fetched_at': snapshot['fetched_at'], 'attribution': snapshot['attribution'],
                'publication_context': publication(owner_item),
            }
        videos.append({
            'library_item_id': identity, 'source_order': index,
            'analysis_version': item['analysis_version'], 'analysis_payload': analysis,
            'publication_context': publication(item), 'performance_ids': owners,
        })
    profile = access.profile(db, company_id)
    prior = ideas.history(db, company_id, body.history_limit)['items'] if body.history_limit else []
    # Bound duplicate-avoidance context and freeze these exact excerpts.
    prior = [{'id': row['id'], 'title': row['title'][:300], 'concept': row['concept'][:2000]} for row in prior]
    payload = jsonable_encoder({
        'videos': videos, 'performance_snapshots': [performance[key] for key in sorted(performance)],
        'company_profile': profile.payload if profile else None,
        'profile_revision_id': profile.revision_id if profile else None,
        'prior_ideas': prior, 'generation_brief': body.generation_brief,
        'target_platforms': sorted(body.target_platforms),
    })
    if len(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, 'Generation evidence exceeds 1 MiB. Select fewer videos.')
    return {'captured_at': captured_at, 'payload': payload,
            'authorized_ids': sorted(set(body.video_ids) | {UUID(key) for key in performance}, key=str)}


def generate(access, session, company_id, body, api_key=None):
    digest = request_hash(body)
    with library.database() as db:
        access.authorize(db, session, company_id, [], write=True)
        claim, saved = ideas.claim_request(db, company_id, body.request_id, digest)
    if saved is not None:
        # Replays need company access, not access to sources that may have unlinked.
        return saved
    try:
        with library.database() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            capture = capture_evidence(db, access, session, company_id, body)
        model = os.environ.get('OPENAI_MODEL', 'gpt-6-sol')
        result = GeneratedIdea.model_validate(generate_idea(capture['payload'], model=model, api_key=api_key))
        with library.database() as db:
            # 006's locks serialize this check + insert against access revocation.
            access.authorize(db, session, company_id, capture['authorized_ids'], write=True)
            return ideas.persist(db, company_id, body, digest, claim, capture, result, model,
                                 RECOMMENDATION_VERSION, EVIDENCE_SCHEMA_VERSION)
    except Exception:
        # Retain request/hash, but permit retry after failures. On connection loss
        # the bounded lease provides recovery; a superseded claim cannot save.
        try:
            with library.database() as db:
                ideas.release_claim(db, company_id, body.request_id, claim)
        except psycopg.Error:
            pass
        raise
