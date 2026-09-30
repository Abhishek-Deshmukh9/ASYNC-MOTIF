"""
Sign-in check for the API, using Supabase Auth.

The browser signs in with Supabase and sends its access token as `Authorization: Bearer <token>`.
Here we verify that token and expose the user. Auth switches on by itself when SUPABASE_URL is set
(override with AUTH_REQUIRED=true/false); with it off, every request is treated as anonymous, so
local development and the test suite need no accounts.
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import httpx
import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient, PyJWKClientError

from app.config import settings

logger = logging.getLogger(__name__)

SIGN_IN_MESSAGE = "Please sign in."


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: Optional[str] = None


def auth_enabled() -> bool:
    if settings.AUTH_REQUIRED is not None:
        return settings.AUTH_REQUIRED
    return bool(settings.SUPABASE_URL)


def _base() -> str:
    return (settings.SUPABASE_URL or "").rstrip("/")


def _issuer() -> str:
    return f"{_base()}/auth/v1"


@lru_cache(maxsize=1)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True)


def _decode_locally(token: str) -> CurrentUser:
    """Verify the signature and claims. Raises jwt.PyJWTError on a bad token, LookupError if we cannot check locally."""
    alg = jwt.get_unverified_header(token).get("alg", "")
    if alg == "HS256":
        if not settings.SUPABASE_JWT_SECRET:
            raise LookupError("no JWT secret configured")
        key = settings.SUPABASE_JWT_SECRET
    elif alg in ("ES256", "RS256", "EdDSA"):
        key = _jwks_client(f"{_issuer()}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
    else:
        raise jwt.InvalidAlgorithmError(f"unsupported algorithm {alg}")

    claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated", issuer=_issuer(), options={"require": ["exp", "sub"]})
    if claims.get("role") != "authenticated":
        raise jwt.InvalidTokenError("not a signed-in user")
    return CurrentUser(id=str(claims["sub"]), email=claims.get("email"))


async def _ask_supabase(token: str) -> CurrentUser:
    """Fallback: let Supabase validate the token (used when the signing key cannot be fetched)."""
    headers = {"Authorization": f"Bearer {token}", "apikey": settings.SUPABASE_PUBLISHABLE_KEY or settings.SUPABASE_SECRET_KEY or ""}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_issuer()}/user", headers=headers)
    if resp.status_code != 200:
        raise jwt.InvalidTokenError("Supabase rejected the token")
    data = resp.json()
    return CurrentUser(id=str(data["id"]), email=data.get("email"))


async def verify_token(token: str) -> CurrentUser:
    try:
        return _decode_locally(token)
    except (LookupError, PyJWKClientError) as exc:
        logger.info("Checking token with Supabase instead (%s)", exc)
        return await _ask_supabase(token)


async def get_current_user(request: Request) -> Optional[CurrentUser]:
    """FastAPI dependency: the signed-in user, or None when auth is off. 401 when auth is on and the token is missing or bad."""
    if not auth_enabled():
        return None
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SIGN_IN_MESSAGE, headers={"WWW-Authenticate": "Bearer"})
    try:
        return await verify_token(token.strip())
    except Exception as exc:
        logger.info("Rejected token: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SIGN_IN_MESSAGE, headers={"WWW-Authenticate": "Bearer"})
