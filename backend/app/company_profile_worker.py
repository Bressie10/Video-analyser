"""Independent PostgreSQL profile worker with lease fencing and one model slot."""

import logging
import os
import threading
from contextlib import asynccontextmanager

from pydantic import ValidationError
from openai import AuthenticationError, BadRequestError, PermissionDeniedError

from app import company_profile_repository as repo
from app import company_profile_evidence as evidence
from app import company_profile_types as p
from app.company_profile_company import get_company_adapter, CompanyLayerUnavailable
from app.company_profile_generator import (
    OpenAIProfileGenerator, GenerationConfigurationError, InvalidProfile, validate, empty_document,
)

logger = logging.getLogger(__name__)


def dependencies_pending(db, job):
    if job['scope'] != 'shared':
        return False
    return db.execute('''SELECT 1 FROM company_profile_jobs j JOIN company_profiles p ON p.id=j.profile_id
        WHERE p.company_id=%s AND p.scope<>'shared' AND j.state IN ('queued','running') LIMIT 1''',
        (job['company_id'],)).fetchone() is not None


def build(job, adapter, generator):
    with repo.database() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        captured = repo.profile(db, job['company_id'], job['scope'])
        pending = dependencies_pending(db, job)
        bundle = evidence.assemble(db, job['company_id'], job['scope'], adapter,
                                   overhead=generator.input_overhead)
        old = db.execute('SELECT * FROM company_profile_revisions WHERE id=%s',
                         (captured['current_revision_id'],)).fetchone()
    if pending:
        with repo.database() as db:
            if repo.live_job(db, job):
                repo.defer(db, job)
        return
    input_hash = evidence.fingerprint(bundle, generator.model)
    with repo.database() as db:
        if not repo.live_job(db, job):
            return
        db.execute('''UPDATE company_profile_jobs SET captured_input_revision=%s,input_hash=%s WHERE id=%s''',
                   (captured['input_revision'], input_hash, job['id']))
    if old and old['input_hash'] == input_hash:
        document = old['document']
    elif not any(ref['kind'] != 'profile' for ref in bundle['manifest']['references'].values()):
        document = empty_document(bundle)
    else:
        document = validate(generator.generate(bundle['payload']), bundle)
    with repo.database() as db:
        repo.lock_company(db, job['company_id'])
        if not repo.live_job(db, job):
            return
        current = repo.profile(db, job['company_id'], job['scope'])
        access = adapter.evidence_access(db, job['company_id'])
        dependencies = evidence.shared(db, job['company_id'])[1] if job['scope'] == 'shared' else {}
        if (current['input_revision'] != captured['input_revision']
                or str(access.version) != bundle['assignment_version']
                or dependencies != bundle['dependencies']
                or dependencies_pending(db, job)):
            repo.defer(db, job)
            return
        repo.publish(db, job, captured, bundle, document, input_hash, generator.model)


def heartbeat(job, done):
    while not done.wait(p.HEARTBEAT_SECONDS):
        try:
            if not repo.renew(job):
                return
        except Exception:
            logger.warning('Profile lease renewal unavailable.')
            return


def process_job(job, adapter=None, generator=None):
    done = threading.Event()
    pulse = threading.Thread(target=heartbeat, args=(job, done), daemon=True)
    pulse.start()
    try:
        build(job, adapter or get_company_adapter(), generator or OpenAIProfileGenerator())
    except (CompanyLayerUnavailable, GenerationConfigurationError, InvalidProfile, ValidationError,
            AuthenticationError, BadRequestError, PermissionDeniedError):
        repo.retry_or_fail(job, permanent=True)
    except Exception:
        repo.retry_or_fail(job)
        logger.warning('Profile generation failed; no provider payload logged.')
    finally:
        done.set()
        pulse.join(timeout=1)


def worker(stop):
    while not stop.is_set():
        try:
            adapter = get_company_adapter()
            with repo.database() as lock_db:
                locked = lock_db.execute('SELECT pg_try_advisory_lock(%s) AS acquired',
                                         (p.WORKER_LOCK,)).fetchone()['acquired']
                lock_db.commit()
                if not locked:
                    stop.wait(p.POLL_SECONDS)
                    continue
                try:
                    while not stop.is_set():
                        repo.schedule_versions()
                        job = repo.claim()
                        if job:
                            process_job(job, adapter)
                        else:
                            stop.wait(p.POLL_SECONDS)
                finally:
                    lock_db.execute('SELECT pg_advisory_unlock(%s)', (p.WORKER_LOCK,))
        except CompanyLayerUnavailable:
            # Disabled until the 006 integration explicitly binds an adapter.
            stop.wait(p.POLL_SECONDS)
        except Exception:
            logger.warning('Profile worker storage unavailable.')
            stop.wait(p.BACKOFF_SECONDS)


@asynccontextmanager
async def lifespan(app):
    from app.meta_library_worker import lifespan as meta_lifespan

    stop = threading.Event()
    thread = None
    async with meta_lifespan(app):
        if os.environ.get('DATABASE_URL') and os.environ.get('COMPANY_PROFILE_WORKER_ENABLED', 'false').lower() == 'true':
            thread = threading.Thread(target=worker, args=(stop,), name='company-profile-worker', daemon=True)
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread:
                thread.join(timeout=2)
