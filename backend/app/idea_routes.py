"""Company-scoped persistent idea workflow, backed by the V3 services."""
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from openai import OpenAIError
from pydantic import AwareDatetime, ValidationError

from app import idea_repository as ideas, idea_service, meta
from app import meta_library_repository as library
from app import company_ownership_repository as ownership
from app.idea_company_access import company_access
from app.idea_generation import InvalidGeneration
from app.idea_models import GenerationRequest, IdeaEdit, IdeaFeedback
from app.meta_routes import _private
from app.recommendations import MissingAPIKeyError

router = APIRouter(prefix='/api/meta/companies/{company_id}')


def respond(operation):
    try:
        result = operation()
        response = JSONResponse(jsonable_encoder(result))
    except HTTPException as error:
        response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
    except ownership.OwnershipNotFound:
        response = JSONResponse({'detail': 'Publication cursor was not found.'}, status_code=404)
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
            after: UUID | None = None, search: str | None = Query(None, max_length=200),
            status: Literal['draft', 'used', 'published', 'discarded'] | None = None,
            feedback: Literal['none', 'liked', 'disliked'] | None = None,
            target_platform: Literal['instagram', 'facebook'] | None = None,
            created_from: AwareDatetime | None = None, created_to: AwareDatetime | None = None,
            access=Depends(company_access)):
    def query(db):
        if created_from is not None and created_to is not None and created_from >= created_to:
            raise HTTPException(422, 'created_from must precede created_to.')
        return ideas.history(db, company_id, limit, after, search=search, status=status,
                             feedback=feedback, target_platform=target_platform,
                             created_from=created_from, created_to=created_to)
    return read_or_edit(request, access, company_id, query)


@router.get('/publication-options')
def publication_options(request: Request, company_id: UUID,
                        limit: int = Query(25, ge=1, le=100), after: UUID | None = None,
                        access=Depends(company_access)):
    return read_or_edit(request, access, company_id,
                        lambda db: ownership.publication_options(db, company_id, limit, after))


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


@router.put('/ideas/{idea_id}/feedback')
def feedback(request: Request, company_id: UUID, idea_id: UUID, body: IdeaFeedback,
             access=Depends(company_access)):
    return read_or_edit(request, access, company_id,
                        lambda db: ideas.set_feedback(db, company_id, idea_id, body.feedback, body.reason), write=True)


@router.get('/ideas/{idea_id}/publications')
def publications(request: Request, company_id: UUID, idea_id: UUID, access=Depends(company_access)):
    # Historical UUID associations do not confer access to current item metadata.
    return read_or_edit(request, access, company_id,
                        lambda db: {'items': ideas.idea(db, company_id, idea_id)['publications']})


@router.put('/ideas/{idea_id}/publications/{library_item_id}')
def add_publication(request: Request, company_id: UUID, idea_id: UUID, library_item_id: UUID,
                    access=Depends(company_access)):
    def link(db):
        ideas.idea(db, company_id, idea_id)
        access.authorize(db, request.cookies.get(meta.SESSION_COOKIE), company_id, [library_item_id], write=True)
        return ideas.add_publication(db, company_id, idea_id, library_item_id)
    return read_or_edit(request, access, company_id, link, write=True)


@router.delete('/ideas/{idea_id}/publications/{library_item_id}')
def remove_publication(request: Request, company_id: UUID, idea_id: UUID, library_item_id: UUID,
                       access=Depends(company_access)):
    return read_or_edit(request, access, company_id,
                        lambda db: ideas.remove_publication(db, company_id, idea_id, library_item_id), write=True)
