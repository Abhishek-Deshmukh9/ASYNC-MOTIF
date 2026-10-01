"""The real pipeline against a real database, with every signal checked against what was stored.
Embeddings and the LLM are replaced (no model downloads in CI); clustering, scoring, saving and the API are real.
Skipped unless TEST_DB=1."""
import functools
import json
import os
import time
import uuid
from types import SimpleNamespace

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core import pipeline as pipeline_module
from app.db.session import engine
from app.main import app

pytestmark = pytest.mark.skipif(os.environ.get("TEST_DB") != "1", reason="needs a database")
SECRET = "test-secret-with-at-least-32-characters!!"
URL = "https://example.supabase.co"
API = "/api/v1"


def vector(axis, jitter):
    v = [0.0] * 384
    v[axis] = 1.0
    v[(axis + 7) % 384] = jitter
    return "[" + ",".join(str(x) for x in v) + "]"


def token(sub):
    return jwt.encode({"sub": sub, "email": "pm@x.com", "role": "authenticated", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")


@pytest.fixture
def db():
    conn = psycopg2.connect(os.environ["SYNC_DATABASE_URL"])
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", SECRET)
    with TestClient(app) as c:
        yield c
        c.portal.call(engine.dispose)


def run_pipeline(client, **kwargs):
    """Run the real pipeline inside the app's own event loop (the database pool belongs to it)."""
    return client.portal.call(functools.partial(pipeline_module.run_ai_pipeline, **kwargs))


def seed(db, project, cluster_axis, n, prefix, arr, churn_every=0, source="email", dated=None):
    for i in range(n):
        meta = {"source_name": f"{source}-{i % 2}"}
        if dated:
            meta["occurred_at"] = dated(i)
        with db.cursor() as cur:
            cur.execute(
                "insert into feedback_items (id, project_id, source_type, content, clean_content, customer_id, customer_tier, arr_value, "
                "churn_risk_flag, embedding, metadata) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)",
                (str(uuid.uuid4()), project, source, f"{prefix} problem {i}", f"{prefix} problem {i}", f"{prefix}-cust-{i}",
                 "enterprise" if arr >= 10000 else "starter", arr, bool(churn_every and i % churn_every == 0),
                 vector(cluster_axis, 0.01 * i), json.dumps(meta)),
            )


@pytest.fixture
def stubbed_models(monkeypatch):
    async def no_embedding(batch_size=50):
        return 0

    async def label(items, exemplars=None):
        prefix = items[0]["content"].split(" problem")[0]
        text = items[0]["content"]
        return SimpleNamespace(title=f"{prefix.title()} theme", problem_statement=f"Customers report {prefix} problems.", cited_quotes=[text])

    monkeypatch.setattr(pipeline_module, "embed_all_unembedded_items", no_embedding)
    monkeypatch.setattr(pipeline_module, "synthesize_cluster_theme", label)


def test_pipeline_stores_a_breakdown_whose_evidence_matches_the_data(client, db, stubbed_models):
    project = f"proj-{uuid.uuid4().hex[:8]}"
    seed(db, project, 3, 9, "billing", arr=50000, churn_every=3)   # 9 enterprise customers, 3 churn-flagged
    seed(db, project, 11, 5, "search", arr=500)                       # 5 small customers
    result = run_pipeline(client, project_id=project, min_cluster_size=4, min_samples=2)
    assert result["dense_clusters_count"] == 2

    me = {"Authorization": f"Bearer {token(str(uuid.uuid4()))}"}
    themes = client.get(f"{API}/themes", params={"project_id": project}, headers=me).json()
    assert [t["title"] for t in themes] == ["Billing theme", "Search theme"]  # the bigger, richer problem ranks first
    top, bottom = themes
    assert top["priority_score"] > bottom["priority_score"]

    b = top["score_breakdown"]
    assert b["rank"] == 1 and b["of"] == 2 and b["profile"] == "b2b_saas"
    signals = {s["key"]: s for s in b["signals"]}
    assert signals["reach"]["raw"] == 9 and len(signals["reach"]["evidence"]) == 8       # evidence is capped, the count is not
    assert signals["revenue"]["raw"] == 9 * 50000
    assert signals["urgency"]["raw"] == pytest.approx(3 / 9, abs=1e-3)
    assert signals["urgency"]["evidence"] and "billing problem" in signals["urgency"]["evidence"][0]["text"]
    assert all(s["why"] and s["how"] for s in b["signals"])
    assert sum(s["points"] for s in b["signals"]) == pytest.approx(b["priority_score"], abs=0.05)
    assert top["priority_score"] == pytest.approx(b["priority_score"], abs=0.01)
    # one project, two sources per feedback channel -> source spread is usable; no event dates -> momentum is dropped, with a reason
    assert "momentum" in {d["key"] for d in b["dropped"]}
    assert "Ranked #1 of 2" in b["verdict"]

    # detail endpoint returns the same breakdown
    one = client.get(f"{API}/themes/{top['id']}", headers=me).json()
    assert one["score_breakdown"]["verdict"] == b["verdict"]


def test_missing_arr_drops_revenue_and_says_why(client, db, stubbed_models):
    project = f"proj-{uuid.uuid4().hex[:8]}"
    seed(db, project, 5, 6, "onboarding", arr=0)
    seed(db, project, 20, 4, "export", arr=0)
    run_pipeline(client, project_id=project, min_cluster_size=4, min_samples=2)
    me = {"Authorization": f"Bearer {token(str(uuid.uuid4()))}"}
    themes = client.get(f"{API}/themes", params={"project_id": project}, headers=me).json()
    b = themes[0]["score_breakdown"]
    assert "revenue" not in {s["key"] for s in b["signals"]}
    reason = next(d["reason"] for d in b["dropped"] if d["key"] == "revenue")
    assert "No customer ARR" in reason
    assert themes[0]["revenue_at_risk"] == 0 and themes[0]["title"] == "Onboarding theme"  # ranked on reach and urgency instead


def test_event_dates_from_metadata_drive_momentum(client, db, stubbed_models):
    project = f"proj-{uuid.uuid4().hex[:8]}"
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    seed(db, project, 8, 6, "crash", arr=100, dated=lambda i: (now - timedelta(days=i)).isoformat())          # all in the last 14 days
    seed(db, project, 30, 6, "typo", arr=100, dated=lambda i: (now - timedelta(days=16 + i)).isoformat())     # all in the 14 days before
    run_pipeline(client, project_id=project, min_cluster_size=4, min_samples=2)
    me = {"Authorization": f"Bearer {token(str(uuid.uuid4()))}"}
    themes = {t["title"]: t for t in client.get(f"{API}/themes", params={"project_id": project}, headers=me).json()}
    crash = {s["key"]: s for s in themes["Crash theme"]["score_breakdown"]["signals"]}["momentum"]
    assert "6 mentions in the last 14 days vs 0 before" in crash["display"] and crash["raw"] == 1.0
    typo = {s["key"]: s for s in themes["Typo theme"]["score_breakdown"]["signals"]}["momentum"]
    assert typo["raw"] == -1.0


def test_dev_tools_profile_can_be_chosen_for_a_run(client, db, stubbed_models):
    project = f"proj-{uuid.uuid4().hex[:8]}"
    seed(db, project, 3, 5, "whale", arr=90000)
    seed(db, project, 11, 9, "crowd", arr=100)
    run_pipeline(client, project_id=project, min_cluster_size=4, min_samples=2, profile="dev_tools")
    me = {"Authorization": f"Bearer {token(str(uuid.uuid4()))}"}
    themes = client.get(f"{API}/themes", params={"project_id": project}, headers=me).json()
    assert themes[0]["title"] == "Crowd theme" and themes[0]["score_breakdown"]["profile_label"] == "Developer tools"
    bad = client.post(f"{API}/pipeline/run", headers=me, json={"project_id": project, "profile": "nonsense"})
    assert bad.status_code == 422


def test_evidence_count_matches_the_messages_the_quotes_were_verified_in(client, db, stubbed_models, monkeypatch):
    project = f"proj-{uuid.uuid4().hex[:8]}"
    seed(db, project, 3, 6, "sync", arr=500)
    seed(db, project, 11, 5, "login", arr=500)

    async def one_quote_many_messages(items, exemplars=None):
        prefix = items[0]["content"].split(" problem")[0]
        # one short quote that appears word for word in every message of the theme
        return SimpleNamespace(title=f"{prefix.title()} theme", problem_statement="x", cited_quotes=[f"{prefix} problem"])

    monkeypatch.setattr(pipeline_module, "synthesize_cluster_theme", one_quote_many_messages)
    run_pipeline(client, project_id=project, min_cluster_size=4, min_samples=2)
    me = {"Authorization": f"Bearer {token(str(uuid.uuid4()))}"}
    themes = {t["title"]: t for t in client.get(f"{API}/themes", params={"project_id": project}, headers=me).json()}
    sync = themes["Sync theme"]
    assert len(sync["cited_quotes"]) == 6                                   # what the card shows
    assert sync["score_breakdown"]["confidence"]["verified_quotes"] == 6    # what the score uses
    assert sync["score_breakdown"]["confidence"]["level"] == "supported"
    assert "Thin evidence" not in sync["score_breakdown"]["verdict"]
