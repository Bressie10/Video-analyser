"""Persistent ideas bound to 006 ownership and 007 immutable profile revisions."""
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import HTTPException, Request

from app import company_ownership_repository as ownership
from app import company_profile_repository as profiles
from app import meta_library_repository as library


@dataclass(frozen=True)
class ProfileEvidence:
    revision_id: UUID
    payload: dict


class CompanyAccess(Protocol):
    def authorize(self, db, session: str | None, company_id: UUID,
                  item_ids: list[UUID], *, write: bool) -> None:
        """Lock live session/company/content access until the supplied db commits."""
        ...

    def performance(self, db, company_id: UUID, item_id: UUID) -> list[dict]:
        """Return only directly owned metric snapshots, after authorization."""
        ...

    def profile(self, db, company_id: UUID) -> ProfileEvidence | None:
        """Read the usable shared revision and its exact dependency revision IDs."""
        ...

    def revalidate(self, db, company_id: UUID, capture: dict) -> None:
        """Recheck metric ownership and captured profile access before persistence."""
        ...


class OwnershipIdeaAccess:
    def authorize(self, db, session, company_id, item_ids, *, write):
        # 006 has one connection-level owner, with identical read/write rights.
        # Both locks conflict with disconnect/session deletion. Ownership mutations
        # take the connection FOR UPDATE before changing company/account/ad rows.
        connection = db.execute('''SELECT c.id FROM meta_connections c
            JOIN meta_sessions s ON s.connection_id=c.id
            WHERE s.token_hash=%s AND s.expires_at>clock_timestamp()
            AND c.status='connected' AND c.expires_at>clock_timestamp()
            FOR SHARE OF c,s''', (library.token_hash(session or ''),)).fetchone()
        if connection is None:
            raise HTTPException(401, 'Reconnect Meta to continue.')
        try:
            ownership.require_active_company(db, connection['id'], company_id)
            for identity in sorted(set(item_ids), key=str):
                item = ownership.get_item(db, connection['id'], company_id, identity)
                # A legacy FK to another connection's analysis is never evidence.
                raw = db.execute('SELECT video_id FROM meta_library_items WHERE id=%s', (identity,)).fetchone()
                if raw['video_id'] and not item['video_id']:
                    raise ownership.OwnershipNotFound()
        except (ownership.CompanyNotFound, ownership.OwnershipNotFound):
            raise HTTPException(404, 'Company content was not found.') from None

    def _connection(self, db, company_id):
        # Only used after authorize in the same transaction, under its locks.
        return db.execute('SELECT connection_id FROM companies WHERE id=%s',
                          (company_id,)).fetchone()['connection_id']

    def performance(self, db, company_id, item_id):
        return ownership.performance(db, self._connection(db, company_id), company_id, item_id)

    def profile(self, db, company_id):
        # Shared intelligence already combines the platform revisions. Suppressed
        # profiles (including dependencies) cannot be used for new generations.
        rows = db.execute('SELECT * FROM company_profiles WHERE company_id=%s', (company_id,)).fetchall()
        shared = next((row for row in rows if row['scope'] == 'shared'), None)
        if not shared or not shared['current_revision_id'] or any(row['suppressed'] for row in rows):
            return None
        revision = db.execute('SELECT * FROM company_profile_revisions WHERE profile_id=%s AND id=%s',
                              (shared['id'], shared['current_revision_id'])).fetchone()
        ids = {'shared': str(revision['id'])}
        ids.update({scope: dep['revision_id'] for scope, dep in revision['dependencies'].items()
                    if dep.get('revision_id')})
        return ProfileEvidence(revision['id'], {
            'scope': 'shared', 'document': revision['document'], 'revision_ids': ids,
        })

    def revalidate(self, db, company_id, capture):
        payload = capture['payload']
        owners = [UUID(row['library_item_id']) for row in payload['performance_snapshots']]
        rows = db.execute(ownership.COMPANY_SCOPE_SQL +
            'SELECT id FROM direct_items WHERE id=ANY(%(owners)s)',
            dict(connection_id=self._connection(db, company_id), company_id=company_id, owners=owners)).fetchall()
        if {row['id'] for row in rows} != set(owners):
            raise HTTPException(404, 'Performance evidence was not found.')
        if payload['profile_revision_id']:
            # Serialize against profile suppression/publication as well as 006
            # ownership changes. Do not accept an old profile after remove/restore.
            profiles.lock_company(db, company_id)
            current = self.profile(db, company_id)
            if current is None or str(current.revision_id) != payload['profile_revision_id']:
                raise HTTPException(409, 'Company profile changed; retry generation.')


_default_access = OwnershipIdeaAccess()


def company_access(request: Request) -> CompanyAccess:
    adapter = getattr(request.app.state, 'idea_company_access', _default_access)
    if adapter is None:
        raise HTTPException(503, 'Company authorization integration is not configured.')
    return adapter
