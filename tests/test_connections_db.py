"""End to end against a real database: connect, sync, re-sync, edit, remove, and privacy between accounts.
Skipped unless TEST_DB=1 (it needs a Postgres with pgvector and the migrations applied)."""
import os
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.integrations import PROVIDERS, Provider, RemoteDoc
from app.db.session import engine
from app.main import app

pytestmark = pytest.mark.skipif(os.environ.get("TEST_DB") != "1", reason="needs a database")
SECRET = "test-secret-with-at-least-32-characters!!"
URL = "https://example.supabase.co"
PRISTINE = {"p1": ("Onboarding calls", "Admins find onboarding confusing. Setup takes too long for new admins. They ask for a guided tour."), "p2": ("Billing notes", "The billing page is slow. Invoices fail to download for annual plans.")}
REMOTE = {"pages": dict(PRISTINE)}


class FakeNotion(Provider):
    name, label = "notion", "Notion"

    async def validate(self):
        if self.credentials.get("token") != "good":
            from app.integrations import ProviderError
            raise ProviderError("Notion rejected this token. Copy the integration secret again.")
        return {"display_name": "Acme HQ"}

    async def options(self):
        return [{"id": k, "name": v[0]} for k, v in REMOTE["pages"].items()]

    async def documents(self, config):
        for pid, (title, body) in REMOTE["pages"].items():
            yield RemoteDoc(external_id=pid, title=title, url=f"https://notion.so/{pid}", kind="note", text=f"# {title}\n\n{body}")


def token(sub):
    return jwt.encode({"sub": sub, "email": f"{sub[:4]}@x.com", "role": "authenticated", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "CONNECTOR_ENCRYPTION_KEY", "test-encryption-key-long-enough")
    monkeypatch.setitem(PROVIDERS, "notion", FakeNotion)
    REMOTE["pages"] = dict(PRISTINE)
    with TestClient(app) as c:
        yield c
        c.portal.call(engine.dispose)  # connections belong to this client's event loop


def h(user):
    return {"Authorization": f"Bearer {token(user)}"}


def test_connect_sync_update_remove_and_privacy(client):
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
    project = str(uuid.uuid4())

    bad = client.post("/api/v1/connections", headers=h(alice), json={"project_id": project, "project_name": "Atlas", "provider": "notion", "credentials": {"token": "bad"}})
    assert bad.status_code == 400 and "rejected this token" in bad.json()["detail"]

    created = client.post("/api/v1/connections", headers=h(alice), json={"project_id": project, "project_name": "Atlas", "provider": "notion", "credentials": {"token": "good"}})
    assert created.status_code == 201, created.text
    conn = created.json()
    assert conn["display_name"] == "Acme HQ" and "credentials" not in conn and "good" not in created.text
    cid = conn["id"]

    # first sync imports both pages as sources with passages
    first = client.post(f"/api/v1/connections/{cid}/sync", headers=h(alice)).json()
    assert (first["imported"], first["unchanged"], first["failed"]) == (2, 0, 0) and first["passages"] >= 2
    sources = client.get(f"/api/v1/sources?project_id={project}", headers=h(alice)).json()
    assert {s["title"] for s in sources} == {"Onboarding calls", "Billing notes"}
    assert all(s["connection_id"] == cid and s["passages"] >= 1 for s in sources)

    # second sync with nothing changed does nothing
    again = client.post(f"/api/v1/connections/{cid}/sync", headers=h(alice)).json()
    assert (again["imported"], again["updated"], again["unchanged"]) == (0, 0, 2)

    # an edited page replaces its passages, a deleted page disappears
    REMOTE["pages"]["p1"] = ("Onboarding calls", "Admins now love onboarding.")
    del REMOTE["pages"]["p2"]
    third = client.post(f"/api/v1/connections/{cid}/sync", headers=h(alice)).json()
    assert (third["updated"], third["removed"]) == (1, 1)
    sources = client.get(f"/api/v1/sources?project_id={project}", headers=h(alice)).json()
    assert [s["title"] for s in sources] == ["Onboarding calls"]

    listed = client.get(f"/api/v1/connections?project_id={project}", headers=h(alice)).json()
    assert listed[0]["sources"] == 1 and listed[0]["last_synced_at"] and listed[0]["status"] == "active"

    # another account can neither see nor use it
    assert client.get(f"/api/v1/connections?project_id={project}", headers=h(bob)).status_code == 404
    assert client.post(f"/api/v1/connections/{cid}/sync", headers=h(bob)).status_code == 404
    assert client.delete(f"/api/v1/connections/{cid}", headers=h(bob)).status_code == 404
    assert client.post("/api/v1/connections", headers=h(bob), json={"project_id": project, "provider": "notion", "credentials": {"token": "good"}}).status_code == 404
    assert client.get(f"/api/v1/connections?project_id={project}").status_code == 401

    # disconnecting keeps the sources unless asked
    kept = client.delete(f"/api/v1/connections/{cid}", headers=h(alice)).json()
    assert kept["sources_removed"] == 0
    assert len(client.get(f"/api/v1/sources?project_id={project}", headers=h(alice)).json()) == 1


def test_disconnect_can_remove_sources(client):
    alice, project = str(uuid.uuid4()), str(uuid.uuid4())
    cid = client.post("/api/v1/connections", headers=h(alice), json={"project_id": project, "provider": "notion", "credentials": {"token": "good"}}).json()["id"]
    client.post(f"/api/v1/connections/{cid}/sync", headers=h(alice))
    out = client.delete(f"/api/v1/connections/{cid}?remove_sources=true", headers=h(alice)).json()
    assert out["sources_removed"] == 2
    assert client.get(f"/api/v1/sources?project_id={project}", headers=h(alice)).json() == []
