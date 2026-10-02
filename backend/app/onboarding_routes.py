"""Authenticated V7 onboarding state and explicit UX mutations."""

from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import AuthenticatedUser, require_authenticated_user
from app.auth_dependencies import application_database
from app import onboarding_repository as repo

router = APIRouter(prefix='/api/me/onboarding', tags=['onboarding'])


class CompanySelection(BaseModel):
    company_id: UUID


@router.get('')
def onboarding(user: AuthenticatedUser = Depends(require_authenticated_user)):
    with application_database() as db:
        return repo.get_state(db, user.user_id)


@router.post('/welcome')
def welcome(user: AuthenticatedUser = Depends(require_authenticated_user)):
    with application_database() as db:
        return repo.mark(db, user.user_id, 'welcome_seen_at')


@router.post('/skip')
def skip(user: AuthenticatedUser = Depends(require_authenticated_user)):
    with application_database() as db:
        return repo.mark(db, user.user_id, 'onboarding_skipped_at')


@router.put('/company')
def select_company(body: CompanySelection,
                   user: AuthenticatedUser = Depends(require_authenticated_user)):
    with application_database() as db:
        return repo.select_company(db, user.user_id, body.company_id)
