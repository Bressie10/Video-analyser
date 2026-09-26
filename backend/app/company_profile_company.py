"""Integration seam for migration 006. No connection-based ownership fallback."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class CompanyLayerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CompanyEvidenceAccess:
    account_ids: tuple[UUID, ...]
    version: str


class CompanyAdapter(Protocol):
    def authorize(self, db, request, company_id: UUID, *, write: bool) -> None:
        """Raise HTTPException(404) for missing/inaccessible company; 401 if signed out."""
        ...

    def evidence_access(self, db, company_id: UUID) -> CompanyEvidenceAccess:
        """Return assigned account IDs and a monotonic assignment generation.

        Use the supplied transaction. Raise for unavailable/deleted companies.
        Assignment writers must invalidate profiles in the same transaction.
        """
        ...


_adapter: CompanyAdapter | None = None


def bind_company_adapter(adapter: CompanyAdapter | None):
    global _adapter
    _adapter = adapter


def get_company_adapter() -> CompanyAdapter:
    if _adapter is None:
        raise CompanyLayerUnavailable('Company profile integration is not configured.')
    return _adapter
