"""Membership-authorized management API preserving company ownership semantics."""

from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import company_ownership_repository as repo
from app import auth_repository as auth, meta_library_repository as library
from app.company_authorization import authenticated_request, authorize

router = APIRouter(prefix='/api', tags=['company management'], dependencies=[Depends(authenticated_request)])


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


def respond(request, operation, *, write=False, status=200, company_id=None,
            owner=False, include_archived=False, target_company_id=None, account_id=None):
    try:
        user = request.state.company_user
        with library.database() as db, db.transaction():
            connection_id = None
            if company_id is not None:
                # Linking chooses a provider connection through an owned account,
                # and binds a disconnected company explicitly in this transaction.
                account = None
                if account_id is not None:
                    account = db.execute('SELECT connection_id FROM meta_accounts WHERE id=%s',
                                         (account_id,)).fetchone()
                company = authorize(db, user, company_id, write=write, owner=owner,
                                    include_archived=include_archived,
                                    target_company_id=target_company_id,
                                    connection_id=account['connection_id'] if account else None)
                connection_id = company['connection_id']
                if account_id is not None:
                    if account is None:
                        raise repo.OwnershipNotFound()
                    try:
                        auth.require_owned_meta_connection(db, user.user_id, account['connection_id'])
                    except auth.CompanyAccessDenied:
                        raise repo.OwnershipNotFound() from None
                    if connection_id is None:
                        connection_id = account['connection_id']
                        db.execute('UPDATE companies SET connection_id=%s WHERE id=%s',
                                   (connection_id, company_id))
                    elif connection_id != account['connection_id']:
                        raise repo.OwnershipNotFound()
            result = operation(db, connection_id)
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
    def operation(db, connection):
        # One snapshot joins verified membership, company and linked accounts.
        # Avoid acquiring multiple connection/company locks in per-company order.
        rows = db.execute('''SELECT c.id,c.name,c.archived_at,
            (SELECT jsonb_agg(to_jsonb(a) ORDER BY a.platform,a.id)
             FROM company_accounts ca JOIN meta_accounts a
             ON a.id=ca.account_id AND a.connection_id=ca.connection_id
             WHERE ca.company_id=c.id AND ca.connection_id=c.connection_id) AS accounts
            FROM companies c JOIN company_memberships m ON m.company_id=c.id
            WHERE m.user_id=%s AND (%s OR c.archived_at IS NULL)
            ORDER BY c.created_at,c.id''', (request.state.company_user.user_id, include_archived)).fetchall()
        return {'companies': [{'company_id': row['id'], 'name': row['name'],
                               'archived': row['archived_at'] is not None,
                               'accounts': [repo._account_summary(account) for account in row['accounts'] or []]}
                              for row in rows]}
    return respond(request, operation)


@router.post('/companies', status_code=201)
def create(request: Request, body: CompanyName):
    def operation(db, connection):
        company = auth.create_company_for_user(db, request.state.company_user.user_id, body.name)
        return repo.company_summary(db, connection, company['id'])
    return respond(request, operation, write=True, status=201)


@router.get('/companies/{company_id}')
def company(request: Request, company_id: UUID):
    return respond(request, lambda db, connection: repo.company_summary(db, connection, company_id),
                   company_id=company_id, include_archived=True)


def change_company(request, company_id, mutation, *, include_archived=False, account_id=None):
    def operation(db, connection):
        mutation(db, connection, company_id)
        return repo.company_summary(db, connection, company_id)
    return respond(request, operation, write=True, company_id=company_id, owner=True,
                   include_archived=include_archived, account_id=account_id)


@router.patch('/companies/{company_id}')
def rename(request: Request, company_id: UUID, body: CompanyName):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.rename_company(db, connection, company, body.name))


@router.post('/companies/{company_id}/archive')
def archive(request: Request, company_id: UUID):
    return change_company(request, company_id, repo.set_company_archived, include_archived=True)


@router.post('/companies/{company_id}/restore')
def restore(request: Request, company_id: UUID):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.set_company_archived(db, connection, company, archived=False), include_archived=True)


@router.get('/meta/accounts')
def accounts(request: Request):
    def operation(db, connection):
        user_id = request.state.company_user.user_id
        connections = db.execute('SELECT id FROM meta_connections WHERE owner_user_id=%s ORDER BY id FOR SHARE',
                                 (user_id,)).fetchall()
        visible = {row['company_id'] for row in db.execute(
            'SELECT company_id FROM company_memberships WHERE user_id=%s FOR SHARE', (user_id,)).fetchall()}
        accounts = []
        for row in connections:
            for account in repo.list_available_accounts(db, row['id']):
                # Do not expose unclaimed/other users' company IDs or names.
                if account['organic_owner'] and account['organic_owner']['company_id'] not in visible:
                    continue
                accounts.append(account)
        return {'accounts': accounts}
    return respond(request, operation)


@router.put('/companies/{company_id}/accounts/{account_id}')
def link_account(request: Request, company_id: UUID, account_id: UUID):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.link_account(db, connection, company, account_id), account_id=account_id)


@router.delete('/companies/{company_id}/accounts/{account_id}')
def unlink_account(request: Request, company_id: UUID, account_id: UUID):
    return change_company(request, company_id,
                          lambda db, connection, company: repo.unlink_account(db, connection, company, account_id))


@router.get('/companies/{company_id}/accounts/{account_id}/ads')
def assignable_ads(request: Request, company_id: UUID, account_id: UUID):
    return respond(request, lambda db, connection: {
        'ads': repo.list_assignable_ads(db, connection, company_id, account_id)},
        company_id=company_id, owner=True)


def change_ad(request, company_id, ad_item_id, mutation, *, target_company_id=None):
    def operation(db, connection):
        mutation(db, connection, company_id, ad_item_id)
        return {'ok': True}
    return respond(request, operation, write=True, company_id=company_id, owner=True,
                   target_company_id=target_company_id)


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
                         db, connection, company, body.target_company_id, ad), target_company_id=body.target_company_id)


@router.get('/companies/{company_id}/content')
def content(request: Request, company_id: UUID, analyzed_only: bool = False,
            platform: Literal['facebook', 'instagram', 'meta_ads'] | None = None,
            content_type: Literal['video', 'reel', 'ad'] | None = None,
            search: str | None = Query(None, min_length=1, max_length=200),
            published_from: datetime | None = None, published_to: datetime | None = None,
            limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
            sort: Literal['published_at'] = 'published_at',
            order: Literal['asc', 'desc'] = 'desc'):
    from app.company_content_repository import list_content

    def operation(db, connection):
        # Authenticate and authorize even when the date range is invalid.
        repo.require_active_company(db, connection, company_id)
        dates = (published_from, published_to)
        if any(value is not None and value.utcoffset() is None for value in dates):
            raise HTTPException(422, 'Publish timestamps must include a timezone.')
        if all(value is not None for value in dates) and published_from > published_to:
            raise HTTPException(422, 'published_from must not be after published_to.')
        return list_content(db, connection, company_id, analyzed_only=analyzed_only,
                            platform=platform, content_type=content_type,
                            search=search.strip() if search else None,
                            published_from=published_from, published_to=published_to,
                            limit=limit, offset=offset, order=order)
    return respond(request, operation, company_id=company_id)
