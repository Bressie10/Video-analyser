"""V3 company-scoped generation, history, evidence and in-place editing."""
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from openai import OpenAIError
from pydantic import ValidationError

from app import idea_repository as ideas, idea_service, meta
from app import meta_library_repository as library
from app.idea_company_access import company_access
from app.idea_generation import InvalidGeneration
from app.idea_models import GenerationRequest, IdeaEdit
from app.meta_routes import _private
from app.recommendations import MissingAPIKeyError

router = APIRouter(prefix='/api/meta/companies/{company_id}')


def respond(operation):
    try:
        result = operation()
        response = JSONResponse(jsonable_encoder(result))
    except HTTPException as error:
        response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
    except MissingAPIKeyError:
        response = JSONResponse({'detail': 'OpenAI API key is not configured.'}, status_code=503)
    except (OpenAIError, InvalidGeneration, ValidationError):
        response = JSONResponse({'detail': 'OpenAI did not return a complete valid idea.'}, status_code=502)
    except (psycopg.Error, ValueError):
        response = JSONResponse({'detail': 'Idea storage is unavailable.'}, status_code=503)
    return _private(response)


@router.post('/recommendations')
def generate(request: Request, company_id: UUID, body: GenerationRequest,
             access=Depends(company_access),
             api_key: str | None = Header(default=None, alias='X-OpenAI-API-Key')):
    return respond(lambda: idea_service.generate(access, request.cookies.get(meta.SESSION_COOKIE),
                                                company_id, body, api_key))


def read_or_edit(request, access, company_id, operation, *, write=False):
    def run():
        with library.database() as db:
            access.authorize(db, request.cookies.get(meta.SESSION_COOKIE), company_id, [], write=write)
            return operation(db)
    return respond(run)


@router.get('/ideas')
def history(request: Request, company_id: UUID, limit: int = Query(25, ge=1, le=100),
            after: UUID | None = None, access=Depends(company_access)):
    return read_or_edit(request, access, company_id, lambda db: ideas.history(db, company_id, limit, after))


@router.get('/ideas/{idea_id}')
def detail(request: Request, company_id: UUID, idea_id: UUID, access=Depends(company_access)):
    return read_or_edit(request, access, company_id, lambda db: ideas.idea(db, company_id, idea_id))


@router.get('/ideas/{idea_id}/evidence')
def evidence(request: Request, company_id: UUID, idea_id: UUID, access=Depends(company_access)):
    return read_or_edit(request, access, company_id, lambda db: ideas.frozen_evidence(db, company_id, idea_id))


@router.patch('/ideas/{idea_id}')
def edit(request: Request, company_id: UUID, idea_id: UUID, body: IdeaEdit, access=Depends(company_access)):
    return read_or_edit(request, access, company_id,
                        lambda db: ideas.edit(db, company_id, idea_id, body.model_dump(exclude_unset=True)), write=True)
