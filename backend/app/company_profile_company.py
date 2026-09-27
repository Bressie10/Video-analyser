"""006-backed company authorization and effective ownership for profile evidence."""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.company_authorization import authorize
from app import company_ownership_repository as ownership


class CompanyLayerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CompanyEvidenceAccess:
    account_ids: tuple[UUID, ...]
    version: str
    connection_id: UUID


class CompanyAdapter(Protocol):
    def authorize(self, db, request, company_id: UUID, *, write: bool) -> None:
        """Require a verified user and active membership; members may refresh."""
        ...

    def evidence_access(self, db, company_id: UUID) -> CompanyEvidenceAccess:
        """Trusted jobs only: resolve active ownership in the supplied transaction.

        Account IDs are provenance, never an authorization predicate for ads.
        Version hashes effective ownership; transactional profile input counters
        independently fence every ownership event, including remove/restore ABA.
        """
        ...


class OwnershipCompanyAdapter:
    def authorize(self, db, request, company_id, *, write):
        authorize(db, request.state.company_user, company_id, write=write)

    def evidence_access(self, db, company_id):
        # HTTP callers must authorize first; the worker receives the company UUID
        # only from its persisted profile job, never a request-supplied connection.
        company = db.execute('SELECT connection_id FROM companies WHERE id=%s', (company_id,)).fetchone()
        if company is None:
            raise CompanyLayerUnavailable('Company is unavailable.')
        try:
            ownership.require_active_company(db, company['connection_id'], company_id)
        except ownership.CompanyNotFound:
            raise CompanyLayerUnavailable('Company is unavailable.') from None
        links = db.execute('''SELECT account_id,account_platform FROM company_accounts
            WHERE company_id=%s AND connection_id=%s ORDER BY account_id''',
            (company_id, company['connection_id'])).fetchall()
        ads = db.execute('''SELECT ad_item_id,account_id FROM company_ad_assignments
            WHERE company_id=%s AND connection_id=%s ORDER BY ad_item_id''',
            (company_id, company['connection_id'])).fetchall()
        version = hashlib.sha256(json.dumps(
            {'accounts': links, 'ads': ads}, sort_keys=True, default=str,
            separators=(',', ':'),
        ).encode()).hexdigest()
        return CompanyEvidenceAccess(tuple(r['account_id'] for r in links), version, company['connection_id'])


_adapter: CompanyAdapter | None = OwnershipCompanyAdapter()


def bind_company_adapter(adapter: CompanyAdapter | None):
    """Explicit override for tests; None continues to fail closed."""
    global _adapter
    _adapter = adapter


def get_company_adapter() -> CompanyAdapter:
    if _adapter is None:
        raise CompanyLayerUnavailable('Company profile integration is not configured.')
    return _adapter
