"""Real signed local tokens; only JWKS network transport is replaced."""
import time
from uuid import UUID
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from app.auth import SupabaseTokenVerifier

USER_ID = UUID('11111111-1111-4111-8111-111111111111')
OTHER_USER_ID = UUID('22222222-2222-4222-8222-222222222222')


class LocalAuth:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.verifier = SupabaseTokenVerifier('https://test-project.supabase.co', 'authenticated')
        self.jwk = jwt.algorithms.ECAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        self.jwk.update(kid='local-key', alg='ES256', use='sig')

    def claims(self, **overrides):
        return dict(dict(sub=str(USER_ID), iss=self.verifier.issuer, aud='authenticated',
                         exp=int(time.time())+300, iat=int(time.time())-1,
                         role='authenticated', email='example@example.test',
                         is_anonymous=False), **overrides)

    def token(self, **overrides):
        return jwt.encode(self.claims(**overrides), self.key, algorithm='ES256', headers={'kid': 'local-key'})

    def serve_jwks(self):
        return patch.object(self.verifier.jwks, 'fetch_data', return_value={'keys': [self.jwk]})
