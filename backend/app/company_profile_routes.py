"""Company-authorized cached reads and explicit asynchronous refresh requests."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app import company_profile_repository as repo
from app.company_profile_company import get_company_adapter, CompanyLayerUnavailable
from app.company_profile_types import SCOPES, Scope

router = APIRouter(prefix='/api/companies/{company_id}/profiles', tags=['company profiles'])


def respond(request, company_id, operation, *, write=False):
    try:
        adapter = get_company_adapter()
        with repo.database() as db:
            adapter.authorize(db, request, company_id, write=write)
            # Authentication takes the connection lock first; retain that lock
            # through the company lock and read/refresh to fence ownership changes.
            repo.lock_company(db, company_id)
            result = operation(db)
        response = JSONResponse(jsonable_encoder(result), status_code=202 if write else 200)
    except HTTPException as error:
        response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
    except (CompanyLayerUnavailable, psycopg.Error, ValueError):
        response = JSONResponse({'detail': 'Company profiles are unavailable.'}, status_code=503)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@router.get('')
def profiles(request: Request, company_id: UUID):
    return respond(request, company_id, lambda db: {
        'profiles': [repo.read(db, company_id, scope, include_document=False) for scope in SCOPES]})


@router.get('/{scope}')
def profile(request: Request, company_id: UUID, scope: Scope):
    return respond(request, company_id, lambda db: repo.read(db, company_id, scope))


@router.post('/{scope}/refresh', status_code=202)
def refresh(request: Request, company_id: UUID, scope: Scope,
            idempotency_key: str = Header(min_length=1, max_length=128)):
    return respond(request, company_id,
                   lambda db: repo.refresh(db, company_id, scope, idempotency_key), write=True)
