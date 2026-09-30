import asyncio
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.auth import auth_enabled
from app.core.projects import authorize_project, project_uuid, validate_project_id
from app.main import app

SECRET = "test-secret-with-at-least-32-characters!!"
URL = "https://example.supabase.co"


def make_token(**overrides):
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "pm@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": f"{URL}/auth/v1",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, SECRET, algorithm="HS256")


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", SECRET)


client = TestClient(app)


def test_auth_switches_on_with_supabase_url(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", None)
    monkeypatch.setattr(settings, "SUPABASE_URL", None)
    assert auth_enabled() is False
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    assert auth_enabled() is True
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    assert auth_enabled() is False


def test_health_is_public_but_data_needs_sign_in(auth_on):
    assert client.get("/api/v1/health").status_code == 200
    for path in ("/api/v1/themes", "/api/v1/projects", "/api/v1/metrics/eval", "/api/v1/sources?project_id=x", "/api/v1/feedback"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["detail"] == "Please sign in."


def test_rejects_bad_tokens(auth_on):
    bad = {
        "garbage": "not-a-token",
        "expired": make_token(exp=int(time.time()) - 10),
        "wrong audience": make_token(aud="something-else"),
        "wrong issuer": make_token(iss="https://evil.example/auth/v1"),
        "anon role": make_token(role="anon"),
        "no subject": make_token(sub=None),
    }
    for name, token in bad.items():
        r = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, name
    forged = jwt.encode({"sub": "x", "role": "authenticated", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 60}, "another-secret-another-secret-123456", algorithm="HS256")
    assert client.get("/api/v1/projects", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert client.get("/api/v1/projects", headers={"Authorization": "Basic abc"}).status_code == 401


def test_valid_token_reaches_the_endpoint(auth_on, monkeypatch):
    from app.core import auth

    async def fake_verify(token):
        return await asyncio.sleep(0, result=auth._decode_locally(token))

    # a valid token gets past the sign-in check (the request may then fail later without a database, but never with 401)
    r = client.get("/api/v1/health", headers={"Authorization": f"Bearer {make_token()}"})
    assert r.status_code == 200
    user = asyncio.run(auth.verify_token(make_token()))
    assert user.id == "11111111-1111-1111-1111-111111111111" and user.email == "pm@example.com"


def test_project_id_rules():
    assert validate_project_id("  abc ") == "abc"
    for bad in ("", "   ", "__demo__", "x" * 256):
        with pytest.raises(Exception):
            validate_project_id(bad)
    assert project_uuid("same") == project_uuid("same") != project_uuid("other")


def test_authorize_is_a_noop_without_a_user_or_project():
    asyncio.run(authorize_project(None, "any", None))
    from app.core.auth import CurrentUser
    asyncio.run(authorize_project(None, None, CurrentUser(id="1")))
