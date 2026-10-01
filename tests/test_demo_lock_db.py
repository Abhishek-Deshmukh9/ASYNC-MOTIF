"""The shared demo is read-only for signed-in users and can never open a real GitHub issue; a project's
issues go only to its own saved repository. Runs against a real database (TEST_DB=1)."""
import os
import time
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import themes as themes_module
from app.config import settings
from app.db.session import engine
from app.main import app

pytestmark = pytest.mark.skipif(os.environ.get("TEST_DB") != "1", reason="needs a database")
SECRET = "test-secret-with-at-least-32-characters!!"
URL = "https://example.supabase.co"
API = "/api/v1"


def token(sub):
    return jwt.encode({"sub": sub, "email": f"{sub[:4]}@x.com", "role": "authenticated", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")


def h(user):
    return {"Authorization": f"Bearer {token(user)}"}


@pytest.fixture
def db():
    conn = psycopg2.connect(os.environ["SYNC_DATABASE_URL"])
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def calls(monkeypatch):
    sent = []

    async def fake_dispatch(title, body, labels=None, owner=None, repo=None):
        sent.append({"owner": owner, "repo": repo, "title": title})
        return {"issue_number": 7, "issue_url": f"https://github.com/{owner}/{repo}/issues/7", "is_live": True}

    monkeypatch.setattr(themes_module, "dispatch_github_issue", fake_dispatch)
    return sent


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "GITHUB_REPO_OWNER", "acme")
    monkeypatch.setattr(settings, "GITHUB_REPO_NAME", "motif-demo")
    monkeypatch.setattr(settings, "DEMO_WRITABLE", False)
    with TestClient(app) as c:
        yield c
        c.portal.call(engine.dispose)


def seed_theme(db, project_id=None, title="Exports time out"):
    tid = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            "insert into themes (id, cluster_id, project_id, title, summary, revenue_at_risk, affected_accounts_count, status) "
            "values (%s, 1, %s, %s, 'Customers say exports fail.', 1000, 2, 'pending_review')",
            (tid, project_id, title),
        )
    return tid


def row(db, tid):
    with db.cursor() as cur:
        cur.execute("select status, title, github_issue_url from themes where id=%s", (tid,))
        status, title, url = cur.fetchone()
        cur.execute("select count(*) from approval_audit_log where theme_id=%s", (tid,))
        return {"status": status, "title": title, "url": url, "audits": cur.fetchone()[0]}


def make_project(client, user, repo, pid=None):
    pid = pid or str(uuid.uuid4())
    r = client.post(f"{API}/projects", headers=h(user), json={"id": pid, "name": "Atlas", "github_repo": repo})
    assert r.status_code == 201, r.text
    return pid


def test_shared_demo_is_read_only_and_never_opens_an_issue(client, db, calls):
    alice = str(uuid.uuid4())
    tid = seed_theme(db)

    approve = client.post(f"{API}/themes/{tid}/approve", headers=h(alice), json={"pm_user_id": "x", "final_title": "Hijacked", "github_repo": "victim/private"})
    assert approve.status_code == 200, approve.text
    body = approve.json()
    assert body["github_dispatch"] == "simulated" and body["github_issue_url"] is None
    assert "shared demo" in body["github_message"] and body["prd_markdown"]
    assert calls == []  # nothing was sent to GitHub
    assert row(db, tid) == {"status": "pending_review", "title": "Exports time out", "url": None, "audits": 0}  # nothing saved

    assert client.patch(f"{API}/themes/{tid}", headers=h(alice), json={"title": "Hijacked"}).status_code == 403
    assert client.post(f"{API}/themes/{tid}/reject", headers=h(alice)).status_code == 403
    assert row(db, tid)["status"] == "pending_review" and row(db, tid)["audits"] == 0

    # reading is still fine
    assert client.get(f"{API}/themes/{tid}", headers=h(alice)).status_code == 200


def test_operator_can_unlock_the_demo(client, db, calls, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_WRITABLE", True)
    tid = seed_theme(db)
    r = client.post(f"{API}/themes/{tid}/approve", headers=h(str(uuid.uuid4())), json={"pm_user_id": "x"})
    assert r.status_code == 200 and r.json()["github_dispatch"] == "live"
    assert calls == [{"owner": "acme", "repo": "motif-demo", "title": "[MOTIF-THEME] Exports time out"}]
    assert row(db, tid)["status"] == "approved"


def test_project_issue_goes_to_its_saved_repo_not_the_requested_one(client, db, calls):
    alice = str(uuid.uuid4())
    pid = make_project(client, alice, "alice/product")
    tid = seed_theme(db, project_id=pid)
    r = client.post(f"{API}/themes/{tid}/approve", headers=h(alice), json={"pm_user_id": "x", "github_repo": "victim/private"})
    assert r.status_code == 200, r.text
    assert r.json()["github_issue_url"] == "https://github.com/alice/product/issues/7"
    assert [(c["owner"], c["repo"]) for c in calls] == [("alice", "product")]
    assert row(db, tid)["status"] == "approved" and row(db, tid)["audits"] == 1


def test_project_without_a_repo_uses_the_default_not_the_requested_one(client, db, calls):
    alice = str(uuid.uuid4())
    pid = make_project(client, alice, None)
    tid = seed_theme(db, project_id=pid)
    assert client.post(f"{API}/themes/{tid}/approve", headers=h(alice), json={"pm_user_id": "x", "github_repo": "victim/private"}).status_code == 200
    assert [(c["owner"], c["repo"]) for c in calls] == [("acme", "motif-demo")]


def test_own_project_can_still_edit_and_reject_and_others_cannot_touch_it(client, db, calls):
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
    pid = make_project(client, alice, "alice/product")
    tid = seed_theme(db, project_id=pid)
    assert client.patch(f"{API}/themes/{tid}", headers=h(alice), json={"title": "Better title"}).status_code == 200
    assert row(db, tid)["title"] == "Better title"
    assert client.post(f"{API}/themes/{tid}/approve", headers=h(bob), json={"pm_user_id": "x"}).status_code == 404
    assert client.post(f"{API}/themes/{tid}/reject", headers=h(bob)).status_code == 404
    assert calls == []
    assert client.post(f"{API}/themes/{tid}/reject", headers=h(alice)).status_code == 200
    assert row(db, tid)["status"] == "rejected"


def test_project_with_an_old_style_id_still_uses_its_saved_repo(client, db, calls):
    alice = str(uuid.uuid4())
    pid = f"atlas-{uuid.uuid4().hex[:8]}"  # older browsers used ids that are not UUIDs
    make_project(client, alice, "alice/legacy", pid=pid)
    tid = seed_theme(db, project_id=pid)
    assert client.post(f"{API}/themes/{tid}/approve", headers=h(alice), json={"pm_user_id": "x", "github_repo": "victim/private"}).status_code == 200
    assert [(c["owner"], c["repo"]) for c in calls] == [("alice", "legacy")]
