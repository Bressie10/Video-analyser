"""Reusable transaction-scoped FastAPI authorization dependencies."""

from contextlib import contextmanager
from uuid import UUID
import psycopg
from fastapi import Depends, HTTPException

from app.auth import AuthenticatedUser, require_authenticated_user
from app import auth_repository as repo
from app.meta_library_repository import database


@contextmanager
def application_database():
    """Explicit service transaction; writes commit before response construction."""
    try:
        with database() as db:
            yield db
    except repo.CompanyAccessDenied:
        raise HTTPException(403, 'Company access denied.', headers={'Cache-Control': 'no-store'}) from None
    except (psycopg.Error, ValueError):
        raise HTTPException(503, 'Application data is unavailable.', headers={'Cache-Control': 'no-store'}) from None


def authenticated_database(user: AuthenticatedUser = Depends(require_authenticated_user)):
    # Authentication resolves first, even when the database is unavailable.
    with application_database() as db:
        yield db


def require_company_access(company_id: UUID,
                           user: AuthenticatedUser = Depends(require_authenticated_user),
                           db=Depends(authenticated_database)):
    return repo.require_company_access(db, user.user_id, company_id)


def require_company_role(role='owner', *, include_archived=False):
    if role not in ('owner', 'member'):
        raise ValueError('Unsupported company role.')

    def dependency(company_id: UUID,
                   user: AuthenticatedUser = Depends(require_authenticated_user),
                   db=Depends(authenticated_database)):
        return repo.require_company_role(db, user.user_id, company_id,
                                         role=role, include_archived=include_archived)
    return dependency
