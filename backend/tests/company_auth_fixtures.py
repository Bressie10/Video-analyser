"""Signed JWT fixtures for the company cutover; no auth dependency bypass."""
from app.auth import get_token_verifier
from app import auth_repository
from auth_fixtures import LocalAuth, USER_ID, OTHER_USER_ID


def sign_in(test, client):
    auth = LocalAuth()
    transport = auth.serve_jwks()
    transport.start()
    test.addCleanup(transport.stop)
    app = client.app
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_token_verifier] = lambda: auth.verifier
    test.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
    client.headers['Authorization'] = 'Bearer ' + auth.token()
    return auth


def grant(db, companies, *, user_id=USER_ID, role='owner', connection=None):
    auth_repository.ensure_profile(db, user_id)
    for company in companies:
        db.execute('''INSERT INTO company_memberships(company_id,user_id,role) VALUES (%s,%s,%s)
            ON CONFLICT (company_id,user_id) DO UPDATE SET role=EXCLUDED.role''', (company, user_id, role))
    if connection:
        db.execute('UPDATE meta_connections SET owner_user_id=%s WHERE id=%s', (user_id, connection))
