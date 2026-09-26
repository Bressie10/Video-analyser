"""Integration contract for 006 authorization and 007 profile revisions.

No fallback ownership inference: a Meta connection is not a company grant.
The application integrating 006/007 installs its adapter on
app.state.idea_company_access. See PERSISTENT_IDEAS.md for locking requirements.
"""
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class ProfileEvidence:
    revision_id: UUID
    payload: dict


class CompanyAccess(Protocol):
    def authorize(self, db, session: str | None, company_id: UUID,
                  item_ids: list[UUID], *, write: bool) -> None:
        """Validate live session, company permission and ALL items using db.

        Lock the authorization rows against revocation until db commits. Include
        metric owners as well as sources. Raise HTTPException(401/404) on denial.
        An empty item list checks company access only, including history/replay.
        """
        ...

    def profile(self, db, company_id: UUID) -> ProfileEvidence | None:
        """Read current revision and provider-ID-free prompt payload on db."""
        ...


def company_access(request: Request) -> CompanyAccess:
    adapter = getattr(request.app.state, 'idea_company_access', None)
    if adapter is None:
        raise HTTPException(503, 'Company authorization integration is not configured.')
    return adapter
