import unittest
from unittest.mock import patch
from uuid import UUID
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.auth import AuthenticatedUser, get_token_verifier, require_authenticated_user, SupabaseTokenVerifier
from auth_fixtures import LocalAuth, USER_ID, OTHER_USER_ID


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.auth = LocalAuth()
        transport = self.auth.serve_jwks()
        transport.start()
        self.addCleanup(transport.stop)
        app = FastAPI()
        @app.get('/protected')
        def protected(user: AuthenticatedUser = Depends(require_authenticated_user)):
            return {'user_id': str(user.user_id), 'email': user.email}
        app.dependency_overrides[get_token_verifier] = lambda: self.auth.verifier
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def request(self, token=None):
        return self.client.get('/protected', headers={'Authorization': 'Bearer '+(token or self.auth.token())})

    def assert_rejected(self, token):
        response = self.request(token)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json(), {'detail': 'Invalid or expired credentials.'})
        self.assertEqual(response.headers['www-authenticate'], 'Bearer')
        self.assertNotIn(token, response.text)

    def test_valid_uuid_and_safe_email(self):
        user = self.auth.verifier.verify(self.auth.token())
        self.assertIsInstance(user.user_id, UUID)
        self.assertEqual(user.user_id, USER_ID)
        self.assertEqual(set(user.__dataclass_fields__), {'user_id', 'email'})
        self.assertEqual(self.request().status_code, 200)

    def test_missing_credentials(self):
        response = self.client.get('/protected')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail'], 'Authentication required.')

    def test_malformed_headers(self):
        for value in ('', 'Basic abc', 'Bearer', 'Bearer a b'):
            with self.subTest(value=value):
                self.assertEqual(self.client.get('/protected', headers={'Authorization': value}).status_code, 401)
        self.assertEqual(self.client.get('/protected', headers=[('Authorization', 'Bearer a'), ('Authorization', 'Bearer b')]).status_code, 401)

    def test_invalid_token(self):
        self.assert_rejected('not-a-jwt')

    def test_expired(self):
        self.assert_rejected(self.auth.token(exp=1))

    def test_invalid_signature(self):
        wrong = ec.generate_private_key(ec.SECP256R1())
        self.assert_rejected(jwt.encode(self.auth.claims(), wrong, algorithm='ES256', headers={'kid': 'local-key'}))

    def test_wrong_issuer_audience_subject_role_and_time(self):
        for claims in ({'iss': 'https://other.supabase.co/auth/v1'}, {'aud': 'other'},
                       {'sub': 'not-a-uuid'}, {'role': 'service_role'}, {'role': 'anon'},
                       {'is_anonymous': True}, {'iat': 9999999999}, {'nbf': 9999999999}):
            with self.subTest(claims=claims):
                self.assert_rejected(self.auth.token(**claims))

    def test_required_claims(self):
        for field in ('exp', 'iat', 'sub', 'iss', 'aud', 'role'):
            claims = self.auth.claims()
            del claims[field]
            self.assert_rejected(jwt.encode(claims, self.auth.key, algorithm='ES256', headers={'kid': 'local-key'}))

    def test_unsigned_symmetric_and_unknown_key_rejected(self):
        self.assert_rejected(jwt.encode(self.auth.claims(), key=None, algorithm='none'))
        self.assert_rejected(jwt.encode(self.auth.claims(), 'x'*64, algorithm='HS256', headers={'kid': 'local-key'}))
        self.assert_rejected(jwt.encode(self.auth.claims(), self.auth.key, algorithm='ES256', headers={'kid': 'unknown'}))

    def test_request_identity_is_ignored(self):
        response = self.client.request('GET', '/protected?user_id='+str(OTHER_USER_ID),
            headers={'Authorization': 'Bearer '+self.auth.token(), 'X-User-Id': str(OTHER_USER_ID)},
            json={'user_id': str(OTHER_USER_ID)})
        self.assertEqual(response.json()['user_id'], str(USER_ID))

    def test_rs256_supported(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        jwk.update(kid='rsa-key', alg='RS256', use='sig')
        with patch.object(self.auth.verifier.jwks, 'fetch_data', return_value={'keys': [jwk]}):
            self.assertEqual(self.auth.verifier.verify(jwt.encode(self.auth.claims(), key, algorithm='RS256', headers={'kid': 'rsa-key'})).user_id, USER_ID)

    def test_no_email_verification_inferred_from_metadata(self):
        user = self.auth.verifier.verify(self.auth.token(email=None, user_metadata={'email_verified': True}))
        self.assertIsNone(user.email)

    def test_jwks_unavailable_fails_closed(self):
        with patch.object(self.auth.verifier.jwks, 'fetch_data', side_effect=jwt.PyJWKClientConnectionError('private error')):
            response = self.request()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private error', response.text)

    def test_configuration_is_https_server_controlled(self):
        for url in ('', 'http://example.test', 'https://user:pass@example.test', 'https://example.test/path'):
            with self.assertRaises(ValueError):
                SupabaseTokenVerifier(url, 'authenticated')
        with patch.dict('os.environ', {'SUPABASE_URL': ''}):
            with self.assertRaises(HTTPException) as error:
                get_token_verifier()
            self.assertEqual(error.exception.status_code, 503)
