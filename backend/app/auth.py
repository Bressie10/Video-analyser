"""Supabase access-token trust boundary; provider cookies are not identity."""

from dataclasses import dataclass
from functools import lru_cache
import os
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, HTTPException, Request
import jwt
from jwt import PyJWKClient


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    # Signed email is informational, never an authorization key or proof of
    # verification (user_metadata.email_verified is user-editable).
    email: str | None = None


def authentication_error(detail='Invalid or expired credentials.'):
    return HTTPException(401, detail, headers={
        'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'})


class SupabaseTokenVerifier:
    def __init__(self, url: str, audience: str):
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/') or not audience):
            raise ValueError('Invalid Supabase verification configuration.')
        self.issuer = url.rstrip('/') + '/auth/v1'
        self.audience = audience
        # Cache the key SET, not individual keys indefinitely; unknown kid causes
        # a refresh. URL is configured by the server, never a token's jku/iss.
        self.jwks = PyJWKClient(self.issuer + '/.well-known/jwks.json',
                                cache_jwk_set=True, lifespan=300, timeout=5)

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') not in ('ES256', 'RS256') or not isinstance(header.get('kid'), str) or not header['kid']:
                raise jwt.InvalidTokenError()
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=['ES256', 'RS256'],
                audience=self.audience, issuer=self.issuer,
                options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'role']},
            )
            if claims['role'] != 'authenticated' or claims.get('is_anonymous', False) is not False:
                raise jwt.InvalidTokenError()
            user_id = UUID(claims['sub'])
            email = claims.get('email')
            return AuthenticatedUser(user_id, email if isinstance(email, str) and email else None)
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503, 'Authentication is temporarily unavailable.',
                                headers={'Cache-Control': 'no-store'}) from None
        except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
            raise authentication_error() from None


@lru_cache(maxsize=4)
def _verifier(url: str, audience: str):
    return SupabaseTokenVerifier(url, audience)


def get_token_verifier() -> SupabaseTokenVerifier:
    try:
        return _verifier(os.environ.get('SUPABASE_URL', ''),
                         os.environ.get('SUPABASE_JWT_AUDIENCE', 'authenticated'))
    except ValueError:
        raise HTTPException(503, 'Authentication is not configured.',
                            headers={'Cache-Control': 'no-store'}) from None


def bearer_token(request: Request) -> str:
    headers = request.headers.getlist('authorization')
    if not headers:
        raise authentication_error('Authentication required.')
    parts = headers[0].split()
    if len(headers) != 1 or len(parts) != 2 or parts[0].lower() != 'bearer':
        raise authentication_error()
    return parts[1]


def require_authenticated_user(token: str = Depends(bearer_token),
                               verifier: SupabaseTokenVerifier = Depends(get_token_verifier)) -> AuthenticatedUser:
    return verifier.verify(token)
