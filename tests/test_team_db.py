"""Team projects against a real database: invites by email, roles, outsiders, and two people acting on the same
theme at once. Skipped unless TEST_DB=1."""
import asyncio
import os
import time
import uuid

import httpx
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


class Person:
    def __init__(self, name):
        self.id = str(uuid.uuid4())
        self.email = f"{name}-{self.id[:6]}@team.test"

    @property
    def h(self):
        claims = {"sub": self.id, "email": self.email, "role": "authenticated", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 3600}
        return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


@pytest.fixture
def db():
    conn = psycopg2.connect(os.environ["SYNC_DATABASE_URL"])
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def issues(monkeypatch):
    sent = []

    async def fake_dispatch(title, body, labels=None, owner=None, repo=None):
        await asyncio.sleep(0.3)  # a slow GitHub call widens the window for a double approval
        sent.append(title)
        return {"issue_number": len(sent), "issue_url": f"https://github.com/acme/app/issues/{len(sent)}", "is_live": True}

    monkeypatch.setattr(themes_module, "dispatch_github_issue", fake_dispatch)
    return sent


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "GITHUB_REPO_OWNER", "acme")
    monkeypatch.setattr(settings, "GITHUB_REPO_NAME", "app")
    with TestClient(app) as c:
        yield c
        c.portal.call(engine.dispose)


def seed_theme(db, project_id, title):
    tid = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            "insert into themes (id, cluster_id, project_id, title, summary, revenue_at_risk, affected_accounts_count, status) "
            "values (%s, 1, %s, %s, 'Customers report it.', 0, 0, 'pending_review')",
            (tid, project_id, title),
        )
    return tid


@pytest.fixture
def team(client, db):
    """Aanya owns a project; Bob is invited as editor, Carol as viewer; Dave is not invited."""
    aanya, bob, carol, dave = Person("aanya"), Person("bob"), Person("carol"), Person("dave")
    pid = str(uuid.uuid4())
    assert client.post(f"{API}/projects", headers=aanya.h, json={"id": pid, "name": "Atlas"}).status_code == 201
    assert client.post(f"{API}/projects/{pid}/members", headers=aanya.h, json={"email": bob.email.upper(), "role": "editor"}).status_code == 201
    assert client.post(f"{API}/projects/{pid}/members", headers=aanya.h, json={"email": carol.email, "role": "viewer"}).status_code == 201
    return {"aanya": aanya, "bob": bob, "carol": carol, "dave": dave, "pid": pid}


def test_invited_people_see_the_project_with_their_role(client, team):
    pid = team["pid"]
    bob_projects = client.get(f"{API}/projects", headers=team["bob"].h).json()
    shared = [p for p in bob_projects if p["id"] == pid]
    assert shared and shared[0]["role"] == "editor" and shared[0]["owner_email"] == team["aanya"].email
    assert [p["role"] for p in client.get(f"{API}/projects", headers=team["carol"].h).json() if p["id"] == pid] == ["viewer"]
    assert [p["role"] for p in client.get(f"{API}/projects", headers=team["aanya"].h).json() if p["id"] == pid] == ["owner"]

    members = client.get(f"{API}/projects/{pid}/members", headers=team["bob"].h).json()
    assert members["my_role"] == "editor" and members["owner_email"] == team["aanya"].email
    by_email = {m["email"]: m for m in members["members"]}
    assert by_email[team["bob"].email]["status"] == "joined"     # signed in, so the invite was claimed (and stored lower-case)
    assert by_email[team["carol"].email]["status"] == "joined"


def test_outsiders_cannot_tell_the_project_exists(client, team):
    pid, dave = team["pid"], team["dave"]
    assert all(p["id"] != pid for p in client.get(f"{API}/projects", headers=dave.h).json())
    assert client.get(f"{API}/themes", params={"project_id": pid}, headers=dave.h).status_code == 404
    assert client.get(f"{API}/projects/{pid}/members", headers=dave.h).status_code == 404
    assert client.post(f"{API}/projects/{pid}/members", headers=dave.h, json={"email": dave.email}).status_code == 404


def test_viewer_can_read_but_not_change_anything(client, db, team, issues):
    pid, carol = team["pid"], team["carol"]
    tid = seed_theme(db, pid, "Exports time out")
    assert client.get(f"{API}/themes", params={"project_id": pid}, headers=carol.h).status_code == 200
    assert client.get(f"{API}/sources", params={"project_id": pid}, headers=carol.h).status_code == 200
    for response in (
        client.post(f"{API}/themes/{tid}/approve", headers=carol.h, json={"pm_user_id": "x"}),
        client.post(f"{API}/themes/{tid}/reject", headers=carol.h),
        client.patch(f"{API}/themes/{tid}", headers=carol.h, json={"title": "Mine now"}),
        client.post(f"{API}/pipeline/run", headers=carol.h, json={"project_id": pid}),
    ):
        assert response.status_code == 403 and "view-only" in response.json()["detail"]
    assert issues == []


def test_only_the_owner_manages_people_and_tools(client, team):
    pid, bob = team["pid"], team["bob"]
    r = client.post(f"{API}/projects/{pid}/members", headers=bob.h, json={"email": "new@team.test"})
    assert r.status_code == 403 and "owner" in r.json()["detail"]
    r = client.post(f"{API}/connections", headers=bob.h, json={"project_id": pid, "project_name": "Atlas", "provider": "github", "credentials": {"repo": "a/b"}})
    assert r.status_code == 403
    assert client.post(f"{API}/projects", headers=bob.h, json={"id": pid, "name": "Renamed by Bob"}).status_code == 403
    carol_id = next(m["id"] for m in client.get(f"{API}/projects/{pid}/members", headers=bob.h).json()["members"] if m["email"] == team["carol"].email)
    assert client.delete(f"{API}/projects/{pid}/members/{carol_id}", headers=bob.h).status_code == 403


def test_editor_approves_and_everyone_sees_who_did_it(client, db, team, issues):
    pid, bob, aanya = team["pid"], team["bob"], team["aanya"]
    tid = seed_theme(db, pid, "Bulk edit missing")
    r = client.post(f"{API}/themes/{tid}/approve", headers=bob.h, json={"pm_user_id": "x", "final_title": "Add bulk edit"})
    assert r.status_code == 200 and r.json()["github_issue_url"].endswith("/issues/1")

    theme = client.get(f"{API}/themes/{tid}", headers=aanya.h).json()
    approved = next(a for a in theme["activity"] if a["action"] == "approved")
    assert approved["by"] == bob.email and approved["title"] == "Add bulk edit" and approved["changed_title"] is True
    assert approved["at"]
    listed = next(t for t in client.get(f"{API}/themes", params={"project_id": pid}, headers=team["carol"].h).json() if t["id"] == tid)
    assert listed["activity"][0]["by"] == bob.email

    # a second approval, or a reject, after the fact is refused and names who decided
    again = client.post(f"{API}/themes/{tid}/approve", headers=aanya.h, json={"pm_user_id": "x"})
    assert again.status_code == 409 and again.json()["detail"].startswith(f"Already approved by {bob.email}")
    assert client.post(f"{API}/themes/{tid}/reject", headers=aanya.h).status_code == 409
    assert client.patch(f"{API}/themes/{tid}", headers=aanya.h, json={"title": "Too late"}).status_code == 409
    assert issues == ["[MOTIF-THEME] Add bulk edit"]  # exactly one GitHub issue


def test_two_people_approving_at_the_same_moment_create_one_issue(client, db, team, issues):
    pid, bob, aanya = team["pid"], team["bob"], team["aanya"]
    tid = seed_theme(db, pid, "Search misses keywords")

    async def both():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await asyncio.gather(
                ac.post(f"{API}/themes/{tid}/approve", headers=bob.h, json={"pm_user_id": "x"}),
                ac.post(f"{API}/themes/{tid}/approve", headers=aanya.h, json={"pm_user_id": "x"}),
            )

    first, second = client.portal.call(both)
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    loser = first if first.status_code == 409 else second
    assert "Already approved by" in loser.json()["detail"]
    assert len(issues) == 1


def test_status_cannot_be_set_by_editing(client, db, team, issues):
    tid = seed_theme(db, team["pid"], "Pricing unclear")
    r = client.patch(f"{API}/themes/{tid}", headers=team["bob"].h, json={"status": "approved"})
    assert r.status_code == 400 and issues == []


def test_owner_changes_roles_removes_people_and_members_can_leave(client, db, team, issues):
    pid, aanya, bob, carol = team["pid"], team["aanya"], team["bob"], team["carol"]
    members = {m["email"]: m["id"] for m in client.get(f"{API}/projects/{pid}/members", headers=aanya.h).json()["members"]}

    # promote Carol: now she can act
    assert client.patch(f"{API}/projects/{pid}/members/{members[carol.email]}", headers=aanya.h, json={"role": "editor"}).json()["role"] == "editor"
    tid = seed_theme(db, pid, "Dark mode contrast")
    assert client.post(f"{API}/themes/{tid}/reject", headers=carol.h).status_code == 200

    # Carol leaves on her own
    left = client.delete(f"{API}/projects/{pid}/members/{members[carol.email]}", headers=carol.h)
    assert left.status_code == 200 and left.json()["left"] is True
    assert client.get(f"{API}/themes", params={"project_id": pid}, headers=carol.h).status_code == 404

    # Aanya removes Bob
    assert client.delete(f"{API}/projects/{pid}/members/{members[bob.email]}", headers=aanya.h).status_code == 200
    assert all(p["id"] != pid for p in client.get(f"{API}/projects", headers=bob.h).json())


def test_invite_validation(client, team):
    pid, aanya, bob = team["pid"], team["aanya"], team["bob"]
    assert client.post(f"{API}/projects/{pid}/members", headers=aanya.h, json={"email": bob.email}).status_code == 409
    assert client.post(f"{API}/projects/{pid}/members", headers=aanya.h, json={"email": "not-an-email"}).status_code == 422
    assert client.post(f"{API}/projects/{pid}/members", headers=aanya.h, json={"email": "x@team.test", "role": "owner"}).status_code == 422
    assert client.post(f"{API}/projects/{pid}/members", headers=aanya.h, json={"email": aanya.email}).status_code == 400


def test_someone_invited_before_they_ever_signed_up_gets_access_on_first_sign_in(client, team):
    pid, aanya = team["pid"], team["aanya"]
    newcomer = Person("newcomer")
    assert client.post(f"{API}/projects/{pid}/members", headers=aanya.h, json={"email": newcomer.email, "role": "viewer"}).json()["status"] == "invited"
    # first request the newcomer makes is opening the project directly (not the project list)
    assert client.get(f"{API}/themes", params={"project_id": pid}, headers=newcomer.h).status_code == 200
    statuses = {m["email"]: m["status"] for m in client.get(f"{API}/projects/{pid}/members", headers=aanya.h).json()["members"]}
    assert statuses[newcomer.email] == "joined"
