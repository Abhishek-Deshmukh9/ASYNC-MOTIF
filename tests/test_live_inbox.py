"""Live inbox: reading messages, the webhook link, and (with a database) joining a theme and re-ranking.
The pure parts always run; the database part is skipped unless TEST_DB=1. Embeddings are replaced with fixed
vectors so the tests need no model download; matching (pgvector), scoring and saving are real."""
import functools
import json
import os
import time
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core import live_inbox
from app.core import pipeline as pipeline_module
from app.db.session import engine
from app.main import app

SECRET = "test-secret-with-at-least-32-characters!!"
URL = "https://example.supabase.co"
API = "/api/v1"


# ---------------------------------------------------------------- reading a message (no database)

def test_motif_shaped_message():
    m = live_inbox.parse_payload({"text": "  Export   fails\non big files ", "from": "Maya", "source": "Slack", "customer": "Acme", "plan": "enterprise", "arr": "50000", "id": 42})
    assert (m.text.strip(), m.author, m.source, m.customer, m.plan, m.arr, m.external_id) == ("Export   fails\non big files", "Maya", "slack", "Acme", "enterprise", 50000.0, "42")


def test_discord_message_object():
    m = live_inbox.parse_payload({"id": "9", "content": "app crashes on login", "author": {"username": "sam", "global_name": "Sam K"}, "timestamp": "2026-09-30T10:00:00+00:00"})
    assert (m.text, m.author, m.source, m.external_id) == ("app crashes on login", "Sam K", "discord", "9")
    assert m.occurred_at.startswith("2026-09-30T10:00:00")


def test_support_ticket_shape():
    m = live_inbox.parse_payload({"ticket": {"id": "T-1", "description": "VAT id missing", "requester": {"name": "Lena", "email": "l@x.com"}, "created_at": "2026-09-30"}})
    assert (m.text, m.author, m.source, m.external_id) == ("VAT id missing", "Lena", "support", "T-1")


@pytest.mark.parametrize("body", [None, [], "text", {"nope": 1}, {"text": "   "}, {"text": 5}])
def test_unusable_bodies_are_refused_in_words(body):
    with pytest.raises(live_inbox.InboxError):
        live_inbox.parse_payload(body)


@pytest.mark.parametrize("arr", ["abc", -1, 10**10])
def test_bad_arr_is_refused(arr):
    with pytest.raises(live_inbox.InboxError):
        live_inbox.parse_payload({"text": "x problem here", "arr": arr})


def test_unknown_sources_become_other_and_aliases_map():
    assert live_inbox.source_key("Zendesk") == "support"
    assert live_inbox.source_key("App Store") == "review"
    assert live_inbox.source_key("carrier pigeon") == "other"
    assert live_inbox.source_key(None) == "other"


def test_future_dates_are_not_trusted():
    assert live_inbox.parse_payload({"text": "problem here", "occurred_at": "2999-01-01"}).occurred_at is None
    assert live_inbox.parse_payload({"text": "problem here", "occurred_at": "not a date"}).occurred_at is None


def test_quote_is_a_word_for_word_start_of_the_message():
    text = ("word " * 100).strip()
    quote = live_inbox.quote_of(text)
    assert text.startswith(quote) and len(quote) <= live_inbox.QUOTE_CHARS and not quote.endswith(" ")
    assert live_inbox.quote_of("short one") == "short one"


def test_tokens_are_hashed_and_rate_limited():
    token = live_inbox.new_token()
    assert token.startswith(live_inbox.TOKEN_PREFIX) and live_inbox.token_hash(token) != token and len(live_inbox.token_hash(token)) == 64
    key = "rate-" + uuid.uuid4().hex
    assert all(live_inbox.allow_hook(key, limit=3) for _ in range(3))
    assert live_inbox.allow_hook(key, limit=3) is False


# ---------------------------------------------------------------- with a database

needs_db = pytest.mark.skipif(os.environ.get("TEST_DB") != "1", reason="needs a database")


class Person:
    def __init__(self, name):
        self.id = str(uuid.uuid4())
        self.email = f"{name}-{self.id[:6]}@team.test"

    @property
    def h(self):
        claims = {"sub": self.id, "email": self.email, "role": "authenticated", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 3600}
        return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def axis_vector(axis, tilt=0.0, other=1):
    """A unit vector mostly along one axis, tilted toward another by `tilt` (cosine similarity to the pure axis = cos of the angle)."""
    v = [0.0] * 384
    v[axis] = (1 - tilt * tilt) ** 0.5
    v[other] = tilt
    return v


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


@pytest.fixture
def fake_model(monkeypatch):
    """The model maps a few phrases to fixed directions; anything else is unrelated to every theme."""
    directions = {"export": 0, "login": 1}

    def embed(text):
        for word, axis in directions.items():
            if word in text.lower():
                return axis_vector(axis, 0.1, other=100 + axis)
        return axis_vector(50, 0.0, other=51)

    monkeypatch.setattr(live_inbox, "embed_message", embed)


def vector_literal(v):
    return "[" + ",".join(str(x) for x in v) + "]"


def add_item(db, project, text, axis, customer, arr, tier, source="Support ticket", churn=False, tilt=0.0):
    item_id = str(uuid.uuid4())
    meta = {"source_name": source}
    with db.cursor() as cur:
        cur.execute(
            "insert into feedback_items (id, project_id, source_type, content, clean_content, customer_id, customer_tier, arr_value, churn_risk_flag, embedding, metadata) "
            "values (%s,%s,'support',%s,%s,%s,%s,%s,%s,%s::vector,%s)",
            (item_id, project, text, text, customer, tier, arr, churn, vector_literal(axis_vector(axis, tilt, other=100 + axis)), json.dumps(meta)),
        )
    return item_id


@pytest.fixture
def analysed(client, db):
    """A project analysed by the real pipeline: an export problem (small accounts) and a login problem (big accounts)."""
    owner = Person("owner")
    pid = str(uuid.uuid4())
    assert client.post(f"{API}/projects", headers=owner.h, json={"id": pid, "name": "Live"}).status_code == 201
    for i in range(5):
        add_item(db, pid, f"export breaks on big files {i}", 0, f"export-cust-{i}", 1000, "starter", tilt=0.01 * i)
    for i in range(5):
        add_item(db, pid, f"login keeps failing {i}", 1, f"login-cust-{i}", 30000, "enterprise", churn=i == 0, tilt=0.01 * i)

    async def no_embedding(batch_size=50):
        return 0

    pipeline_module.embed_all_unembedded_items, original = no_embedding, pipeline_module.embed_all_unembedded_items

    async def label(items, exemplars=None):
        from types import SimpleNamespace
        key = "export" if "export" in items[0]["content"] else "login"
        quotes = [it["content"] for it in items[:3]]
        return SimpleNamespace(title=f"{key} problem", problem_statement=f"Customers report {key} trouble.", cited_quotes=quotes)

    pipeline_module.synthesize_cluster_theme, original_label = label, pipeline_module.synthesize_cluster_theme
    try:
        result = client.portal.call(functools.partial(pipeline_module.run_ai_pipeline, project_id=pid, min_cluster_size=4, min_samples=2))
    finally:
        pipeline_module.embed_all_unembedded_items = original
        pipeline_module.synthesize_cluster_theme = original_label
    assert result["themes_created"] == 2
    return {"owner": owner, "pid": pid}


def themes(client, owner, pid):
    return {t["title"]: t for t in client.get(f"{API}/themes", params={"project_id": pid}, headers=owner.h).json()}


@needs_db
def test_a_similar_message_joins_its_theme_and_the_ranking_moves(client, fake_model, analysed):
    owner, pid = analysed["owner"], analysed["pid"]
    before = themes(client, owner, pid)
    assert before["login problem"]["score_breakdown"]["rank"] == 1 and before["export problem"]["score_breakdown"]["rank"] == 2

    # Several big, churning export reporters arrive, one at a time
    last, answers = None, []
    for i in range(6):
        r = client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": f"Export is broken again, we will cancel if it stays like this {i}", "source": "support", "customer": f"newco-{i}", "plan": "enterprise", "arr": 90000})
        assert r.status_code == 201, r.text
        last = r.json()
        answers.append(last)
        assert last["match"]["status"] == "joined" and last["match"]["theme_title"] == "export problem"

    after = themes(client, owner, pid)
    export = after["export problem"]
    assert last["match"]["similarity"] >= live_inbox.match_threshold()
    assert export["mention_count"] == before["export problem"]["mention_count"] + 6
    assert export["score_breakdown"]["rank"] == 1 and after["login problem"]["score_breakdown"]["rank"] == 2   # it overtook
    assert export["priority_score"] > before["export problem"]["priority_score"]
    assert last["match"]["rank_after"] == 1 and last["match"]["of"] == 2
    # exactly one message made the swap, and it said so: export 2 -> 1, login 1 -> 2
    swaps = [a for a in answers if (a["match"]["rank_before"], a["match"]["rank_after"]) == (2, 1)]
    assert len(swaps) == 1
    assert {(m["title"], m["from"], m["to"]) for m in swaps[0]["match"]["moved"]} == {("export problem", 2, 1), ("login problem", 1, 2)}
    assert answers[-1]["match"]["moved"] == []   # later messages only add to the lead
    assert [a["match"]["rank_before"] for a in answers] == sorted((a["match"]["rank_before"] for a in answers), reverse=True)
    # the stored evidence still matches the stored data: points add up to the score
    points = sum(s["points"] for s in export["score_breakdown"]["signals"])
    assert abs(points - export["priority_score"]) < 0.02
    # revenue: 5 starter accounts at $1,000 plus six new accounts at $90,000
    assert export["revenue_at_risk"] == 5 * 1000 + 6 * 90000
    # the new message is quoted word for word on the theme card
    assert any("Export is broken again" in q["quote_text"] for q in export["cited_quotes"])


@needs_db
def test_the_arr_of_a_known_customer_is_taken_from_the_project_not_from_the_sender(client, fake_model, analysed):
    owner, pid = analysed["owner"], analysed["pid"]
    r = client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "login is failing for us again", "customer": "LOGIN-CUST-2"}).json()
    assert r["customer"] == "login-cust-2" and r["arr"] == 30000 and "existing records" in r["arr_from"]
    r = client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "login is failing for someone new", "customer": "Brand New Co"}).json()
    assert r["arr"] == 0 and r["arr_from"] is None   # unknown customers are not given revenue Motif has no basis for


@needs_db
def test_an_unrelated_message_waits_and_changes_nothing(client, fake_model, analysed):
    owner, pid = analysed["owner"], analysed["pid"]
    before = {k: (v["priority_score"], v["mention_count"]) for k, v in themes(client, owner, pid).items()}
    r = client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "love the new logo!"}).json()
    assert r["match"]["status"] == "waiting" and f"needs {round(live_inbox.match_threshold() * 100)}%" in r["match"]["reason"] and r["now_in"] is None
    assert {k: (v["priority_score"], v["mention_count"]) for k, v in themes(client, owner, pid).items()} == before
    feed = client.get(f"{API}/inbox", params={"project_id": pid}, headers=owner.h).json()["items"]
    assert [i["text"] for i in feed] == ["love the new logo!"]


@needs_db
def test_a_project_with_no_themes_keeps_the_message_for_later(client, fake_model):
    owner = Person("fresh")
    pid = str(uuid.uuid4())
    client.post(f"{API}/projects", headers=owner.h, json={"id": pid, "name": "Empty"})
    r = client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "export is broken"}).json()
    assert r["match"]["status"] == "waiting" and "Analyze" in r["match"]["reason"]


@needs_db
def test_a_type_chosen_by_a_pm_survives_a_live_message(client, fake_model, analysed):
    owner, pid = analysed["owner"], analysed["pid"]
    tid = themes(client, owner, pid)["export problem"]["id"]
    assert client.patch(f"{API}/themes/{tid}/type", headers=owner.h, json={"issue_type": "security"}).status_code == 200
    client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "export broke again today"})
    export = themes(client, owner, pid)["export problem"]["score_breakdown"]
    assert export["issue_type"]["type"] == "security" and export["issue_type"]["source"] == "pm" and export["lane"] == "fix_first" and export["rank"] == 1


@needs_db
def test_roles_for_the_app_box(client, fake_model, analysed):
    owner, pid = analysed["owner"], analysed["pid"]
    editor, viewer, outsider = Person("editor"), Person("viewer"), Person("outsider")
    client.post(f"{API}/projects/{pid}/members", headers=owner.h, json={"email": editor.email, "role": "editor"})
    client.post(f"{API}/projects/{pid}/members", headers=owner.h, json={"email": viewer.email, "role": "viewer"})
    body = {"project_id": pid, "text": "login failing again"}
    assert client.post(f"{API}/inbox", headers=editor.h, json=body).status_code == 201
    r = client.post(f"{API}/inbox", headers=viewer.h, json=body)
    assert r.status_code == 403 and "view-only" in r.json()["detail"]
    assert client.post(f"{API}/inbox", headers=outsider.h, json=body).status_code == 404
    assert client.get(f"{API}/inbox", params={"project_id": pid}, headers=outsider.h).status_code == 404
    seen = client.get(f"{API}/inbox", params={"project_id": pid}, headers=viewer.h).json()
    assert seen["can_send"] is False and seen["can_manage_webhook"] is False and len(seen["items"]) == 1
    assert client.get(f"{API}/inbox", params={"project_id": pid}, headers=editor.h).json()["can_manage_webhook"] is False
    assert client.get(f"{API}/inbox", params={"project_id": pid}, headers=owner.h).json()["can_manage_webhook"] is True


@needs_db
def test_the_shared_demo_inbox_is_read_only_for_signed_in_users(client, fake_model):
    r = client.post(f"{API}/inbox", headers=Person("anyone").h, json={"text": "export is broken"})
    assert r.status_code == 403


@needs_db
def test_webhook_link_lifecycle(client, db, fake_model, analysed):
    owner, pid = analysed["owner"], analysed["pid"]
    editor = Person("editor2")
    client.post(f"{API}/projects/{pid}/members", headers=owner.h, json={"email": editor.email, "role": "editor"})
    assert client.post(f"{API}/inbox/webhook", params={"project_id": pid}, headers=editor.h).status_code == 403   # owner only

    link = client.post(f"{API}/inbox/webhook", params={"project_id": pid}, headers=owner.h).json()
    token, path = link["token"], link["path"]
    with db.cursor() as cur:
        cur.execute("select inbox_token_hash, inbox_token_hint from projects where id=%s", (pid,))
        stored, hint = cur.fetchone()
    assert token not in stored and stored == live_inbox.token_hash(token) and hint == token[-4:]   # only a hash is stored

    # no sign-in needed: the link is the credential
    r = client.post(path, json={"content": "Cannot export anything since the update", "author": {"username": "dev1"}, "id": "d-1"})
    assert r.status_code == 201 and r.json()["source"] == "Discord" and r.json()["match"]["theme_title"] == "export problem"
    again = client.post(path, json={"content": "Cannot export anything since the update", "author": {"username": "dev1"}, "id": "d-1"}).json()
    assert again["duplicate"] is True
    assert client.post(path, content=b"{{nope").status_code == 400
    assert client.post(path, json={"nothing": "here"}).status_code == 422
    assert client.post(f"{API}/inbox/hook/motif_in_notarealtoken", json={"text": "export"}).status_code == 404
    feed = client.get(f"{API}/inbox", params={"project_id": pid}, headers=owner.h).json()
    assert feed["webhook"] == {"available": True, "enabled": True, "hint": hint} and len(feed["items"]) == 1

    new_link = client.post(f"{API}/inbox/webhook", params={"project_id": pid}, headers=owner.h).json()   # replacing the link
    assert client.post(path, json={"text": "export is broken"}).status_code == 404
    assert client.post(new_link["path"], json={"text": "export is broken in prod"}).status_code == 201
    assert client.delete(f"{API}/inbox/webhook", params={"project_id": pid}, headers=owner.h).status_code == 200
    assert client.post(new_link["path"], json={"text": "export is broken"}).status_code == 404


@needs_db
def test_webhook_is_rate_limited(client, fake_model, analysed, monkeypatch):
    owner, pid = analysed["owner"], analysed["pid"]
    monkeypatch.setattr(live_inbox, "HOOK_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(live_inbox, "allow_hook", functools.partial(live_inbox.allow_hook, limit=2))
    path = client.post(f"{API}/inbox/webhook", params={"project_id": pid}, headers=owner.h).json()["path"]
    codes = [client.post(path, json={"text": f"login problem number {i}"}).status_code for i in range(4)]
    assert codes == [201, 201, 429, 429]


@needs_db
def test_a_message_sent_during_analysis_waits(client, fake_model, analysed, monkeypatch):
    owner, pid = analysed["owner"], analysed["pid"]
    from app.api.v1.endpoints import pipeline as pipeline_endpoint
    monkeypatch.setitem(pipeline_endpoint._runs, pid, {"status": "running"})
    r = client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "export is broken"}).json()
    assert r["match"]["status"] == "waiting" and "being analysed" in r["match"]["reason"]


@needs_db
def test_a_new_analysis_groups_waiting_messages_and_keeps_them_in_the_feed(client, fake_model, analysed):
    owner, pid = analysed["owner"], analysed["pid"]
    client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "love the new logo!"})
    client.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": "export is broken"})
    items = client.get(f"{API}/inbox", params={"project_id": pid}, headers=owner.h).json()["items"]
    assert {i["text"]: (i["now_in"] or {}).get("title") for i in items} == {"love the new logo!": None, "export is broken": "export problem"}


@needs_db
def test_rescoring_stored_data_gives_the_scores_the_pipeline_stored(client, analysed):
    """The 'before' numbers a live message reports are recomputed from the database, so they must equal what the screen showed."""
    from app.core import rescore as rescore_module
    from app.db.session import AsyncSessionLocal

    pid = analysed["pid"]

    async def recompute():
        async with AsyncSessionLocal() as session:
            peers = await rescore_module.scoring_peers(session, pid, lock=False)
            inputs = await rescore_module.theme_inputs(session, peers, pid)
            sources = await rescore_module.source_names(session, pid)
            again = rescore_module.rescore(inputs, rescore_module.snapshot(peers), rescore_module.profile_of(peers), len(sources))
            return [(p.title, p.score_breakdown["priority_score"], p.score_breakdown["rank"], b["priority_score"], b["rank"]) for p, b in zip(peers, again)]

    rows = client.portal.call(recompute)
    assert len(rows) == 2
    for title, stored_score, stored_rank, new_score, new_rank in rows:
        assert (stored_score, stored_rank) == (new_score, new_rank), title


@needs_db
def test_two_messages_at_the_same_moment_are_both_counted(client, fake_model, analysed):
    import asyncio
    import httpx

    owner, pid = analysed["owner"], analysed["pid"]
    before = themes(client, owner, pid)["export problem"]["mention_count"]

    async def both():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await asyncio.gather(*[
                ac.post(f"{API}/inbox", headers=owner.h, json={"project_id": pid, "text": f"export keeps failing for us {i}", "customer": f"c{i}", "plan": "enterprise", "arr": 50000})
                for i in range(3)
            ])

    answers = client.portal.call(both)
    assert [a.status_code for a in answers] == [201, 201, 201]
    export = themes(client, owner, pid)["export problem"]
    assert export["mention_count"] == before + 3
    assert export["revenue_at_risk"] == 5 * 1000 + 3 * 50000
    assert abs(sum(s["points"] for s in export["score_breakdown"]["signals"]) - export["priority_score"]) < 0.02
    ranks = sorted(t["score_breakdown"]["rank"] for t in themes(client, owner, pid).values())
    assert ranks == [1, 2]


def test_threshold_is_a_setting_and_stays_between_0_and_1(monkeypatch):
    assert live_inbox.match_threshold() == 0.6
    monkeypatch.setattr(settings, "LIVE_MATCH_MIN_SIMILARITY", 0.45)
    assert live_inbox.match_threshold() == 0.45
    monkeypatch.setattr(settings, "LIVE_MATCH_MIN_SIMILARITY", 7)
    assert live_inbox.match_threshold() == 1.0
