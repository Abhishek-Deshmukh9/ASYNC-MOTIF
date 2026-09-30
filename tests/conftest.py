"""Tests run with sign-in off unless a test turns it on (a developer's .env may set SUPABASE_URL)."""
import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _auth_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
