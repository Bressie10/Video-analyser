"""Minimal application identity surface; all other V5 routes remain transitional."""
from fastapi import APIRouter, Depends, Response
from app.auth import AuthenticatedUser, require_authenticated_user
from app.auth_dependencies import authenticated_database, application_database
from app import auth_repository as repo

router = APIRouter(prefix='/api/me', tags=['application identity'])


@router.get('')
def me(response: Response, user: AuthenticatedUser = Depends(require_authenticated_user)):
    # Lazy provisioning is a write: commit before emitting a successful response.
    with application_database() as db:
        profile = repo.ensure_profile(db, user.user_id)
    response.headers['Cache-Control'] = 'private, no-store'
    return {'user_id': user.user_id, 'email': user.email,
            'profile': profile}


@router.get('/companies')
def companies(response: Response, include_archived: bool = False,
              user: AuthenticatedUser = Depends(require_authenticated_user),
              db=Depends(authenticated_database)):
    response.headers['Cache-Control'] = 'private, no-store'
    return {'companies': repo.list_accessible_companies(db, user.user_id,
                                                       include_archived=include_archived)}
