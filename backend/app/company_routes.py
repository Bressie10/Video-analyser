"""V4 management API using the existing Meta session and 006 ownership layer."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import company_ownership_repository as repo
from app import meta, meta_library_repository as library

router = APIRouter(prefix='/api', tags=['company management'])


class CompanyName(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)

    @field_validator('name')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Company name is required.')
        return value.strip()


class Reassignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_company_id: UUID


def respond(request, operation, *, write=False, status=200):
    try:
        session = request.cookies.get(meta.SESSION_COOKIE)
        if not session:
            raise HTTPException(401, 'Reconnect Meta to continue.')
        with library.database() as db:
            # Take the write lock up front, avoiding shared-to-exclusive lock
            # upgrades between concurrent mutations. Lock the session as well so
            # revocation cannot race an authorized mutation's commit.
            mode = 'UPDATE' if write else 'SHARE'
            connection = db.execute(f'''SELECT c.id FROM meta_connections c
                JOIN meta_sessions s ON s.connection_id=c.id
                WHERE s.token_hash=%s AND s.expires_at>clock_timestamp()
                AND c.status='connected' AND c.expires_at>clock_timestamp()
                FOR {mode} OF c,s''', (library.token_hash(session),)).fetchone()
            if connection is None:
                raise HTTPException(401, 'Reconnect Meta to continue.')
            result = operation(db, connection['id'])
        response = JSONResponse(jsonable_encoder(result), status_code=status)
    except HTTPException as error:
        response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
    except repo.CompanyNotFound:
        response = JSONResponse({'detail': 'Company was not found.'}, status_code=404)
    except repo.OwnershipNotFound:
        response = JSONResponse({'detail': 'Company resource was not found.'}, status_code=404)
    except repo.OwnershipConflict as error:
        response = JSONResponse({'detail': str(error)}, status_code=409)
    except (psycopg.Error, ValueError):
        response = JSONResponse({'detail': 'Company management is unavailable.'}, status_code=503)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@router.get('/companies')
def companies(request: Request, include_archived: bool = False):
    return respond(request, lambda db, connection: {'companies': repo.list_company_summaries(
        db, connection, include_archived=include_archived)})


@router.post('/companies', status_code=201)
def create(request: Request, body: CompanyName):
    def operation(db, connection):
        company = repo.create_company(db, connection, body.name)
        return repo.company_summary(db, connection, company['id'])
    return respond(request, operation, write=True, status=201)


@router.get('/companies/{company_id}')
def company(request: Request, company_id: UUID):
    return respond(request, lambda db, connection: repo.company_summary(db, connection, company_id))


def change_company(request, company_id, mutation):
    def operation(db, connection):
        mutation(db, connection, company_id)
        return repo.company_summary(db, connection, company_id)
    return respond(request, operation, write=True)


@router.patch('/companies/{company_id}')
def rename(request: Request, company_id: UUID, body: CompanyName):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.rename_company(db, connection, company, body.name))


@router.post('/companies/{company_id}/archive')
def archive(request: Request, company_id: UUID):
    return change_company(request, company_id, repo.set_company_archived)


@router.post('/companies/{company_id}/restore')
def restore(request: Request, company_id: UUID):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.set_company_archived(db, connection, company, archived=False))


@router.get('/meta/accounts')
def accounts(request: Request):
    return respond(request, lambda db, connection: {'accounts': repo.list_available_accounts(db, connection)})


@router.put('/companies/{company_id}/accounts/{account_id}')
def link_account(request: Request, company_id: UUID, account_id: UUID):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.link_account(db, connection, company, account_id))


@router.delete('/companies/{company_id}/accounts/{account_id}')
def unlink_account(request: Request, company_id: UUID, account_id: UUID):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.unlink_account(db, connection, company, account_id))


@router.get('/companies/{company_id}/accounts/{account_id}/ads')
def assignable_ads(request: Request, company_id: UUID, account_id: UUID):
    return respond(request, lambda db, connection: {
        'ads': repo.list_assignable_ads(db, connection, company_id, account_id)})


def change_ad(request, company_id, ad_item_id, mutation):
    def operation(db, connection):
        mutation(db, connection, company_id, ad_item_id)
        return {'ok': True}
    return respond(request, operation, write=True)


@router.put('/companies/{company_id}/ads/{ad_item_id}')
def assign_ad(request: Request, company_id: UUID, ad_item_id: UUID):
    return change_ad(request, company_id, ad_item_id, repo.assign_ad)


@router.delete('/companies/{company_id}/ads/{ad_item_id}')
def unassign_ad(request: Request, company_id: UUID, ad_item_id: UUID):
    return change_ad(request, company_id, ad_item_id, repo.unassign_ad)


@router.post('/companies/{company_id}/ads/{ad_item_id}/reassign')
def reassign_ad(request: Request, company_id: UUID, ad_item_id: UUID, body: Reassignment):
    return change_ad(request, company_id, ad_item_id,
                     lambda db, connection, company, ad: repo.reassign_ad(
                         db, connection, company, body.target_company_id, ad))
