from fastapi.testclient import TestClient
from app.auth import get_token_verifier
from auth_fixtures import LocalAuth, USER_ID

def install(test, app):
    auth = LocalAuth()
    patcher = auth.serve_jwks()
    patcher.start()
    test.addCleanup(patcher.stop)
    previous = app.dependency_overrides.get(get_token_verifier)
    app.dependency_overrides[get_token_verifier] = lambda: auth.verifier
    def cleanup():
        if previous is None: app.dependency_overrides.pop(get_token_verifier, None)
        else: app.dependency_overrides[get_token_verifier] = previous
    test.addCleanup(cleanup)
    return auth

def client_factory(test, app):
    auth = install(test, app)
    def client(*args, **kwargs):
        return TestClient(*args, **kwargs, headers={'Authorization': 'Bearer '+auth.token()})
    return client
