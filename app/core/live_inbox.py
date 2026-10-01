"""
Live inbox: messages that arrive one at a time, typed into the app or sent to a project's webhook.

A new message is embedded with the pipeline's model (all-MiniLM-L6-v2) and compared, with pgvector cosine
distance, to the messages already in each theme of the latest analysis. It joins the theme holding its most
similar message when that similarity reaches match_threshold(). The project is then re-scored with the same
arithmetic as the pipeline, and the result records why the ranking moved: the theme, the similarity, the closest
existing message, and each theme's rank and score before and after.

HDBSCAN is not re-run per message: it groups all messages at once. A message that is not similar enough to any
theme waits, and is grouped (possibly into a new theme) the next time the project is analysed.
"""
import asyncio
import hashlib
import logging
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core import embeddings
from app.core.normalization import clean_text, detect_churn_intent
from app.core.pipeline import scoring_item
from app.core.ranker import calculate_revenue_at_risk
from app.core.rescore import in_scope, profile_of, rescore, scoring_peers, snapshot, source_names, theme_inputs
from app.models.feedback import FeedbackItem, theme_feedback_associations
from app.models.theme import Theme

logger = logging.getLogger(__name__)

def match_threshold() -> float:
    """
    A message joins a theme when it is at least this similar (cosine, all-MiniLM-L6-v2) to one of the theme's
    messages. Default 0.6 (setting LIVE_MATCH_MIN_SIMILARITY); chosen on held-out messages, see docs/LIVE_INBOX.md.
    """
    return min(max(float(settings.LIVE_MATCH_MIN_SIMILARITY), 0.0), 1.0)


MAX_TEXT_CHARS = 8000
QUOTE_CHARS = 240
FEED_LIMIT = 20
HOOK_LIMIT_PER_MINUTE = 30

SOURCES: Dict[str, str] = {
    "discord": "Discord",
    "support": "Support ticket",
    "slack": "Slack",
    "email": "Email",
    "call": "Call notes",
    "review": "App review",
    "other": "Other",
}
SOURCE_ALIASES = {
    "ticket": "support", "support_ticket": "support", "zendesk": "support", "intercom": "support", "freshdesk": "support",
    "app_store": "review", "play_store": "review", "appstore": "review",
    "calls": "call", "meeting": "call", "transcript": "call", "mail": "email",
}
TIERS = ("enterprise", "growth", "starter", "free")


class InboxError(ValueError):
    """The message can't be accepted; the text says why, in words for the sender."""


@dataclass
class InboxMessage:
    text: str
    source: str = "other"
    author: Optional[str] = None
    customer: Optional[str] = None
    plan: Optional[str] = None
    arr: Optional[float] = None
    external_id: Optional[str] = None
    occurred_at: Optional[str] = None


# ---------------------------------------------------------------- reading a message

def _text_field(value: Any, limit: int) -> Optional[str]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


def source_key(value: Any) -> str:
    key = (_text_field(value, 40) or "other").lower().replace(" ", "_").replace("-", "_")
    key = SOURCE_ALIASES.get(key, key)
    return key if key in SOURCES else "other"


def _event_time(value: Any) -> Optional[str]:
    """An event date sent with the message, if it is a real date and not in the future."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if parsed > datetime.now(timezone.utc) + timedelta(days=1):
        return None
    return parsed.isoformat()


def _number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InboxError('"arr" must be a number, like 50000.')
    if not 0 <= number <= 1_000_000_000:
        raise InboxError('"arr" must be between 0 and 1,000,000,000.')
    return number


def parse_payload(body: Any) -> InboxMessage:
    """
    One message from a webhook body. Accepts Motif's own shape ({"text", "from", "source", "customer", "plan",
    "arr", "id", "occurred_at"}), a Discord message object ({"content", "author": {...}, "id", "timestamp"}),
    or a support ticket ({"ticket": {"description", "requester", "id", "created_at"}}).
    """
    if not isinstance(body, dict):
        raise InboxError('Send one JSON object with a "text" field.')
    author_obj = body.get("author") if isinstance(body.get("author"), dict) else None
    ticket = body.get("ticket") if isinstance(body.get("ticket"), dict) else {}
    requester = ticket.get("requester") if isinstance(ticket.get("requester"), dict) else {}

    text = next((v for v in (body.get("text"), body.get("content"), body.get("message"), body.get("body"), ticket.get("description")) if isinstance(v, str) and v.strip()), None)
    if text is None:
        raise InboxError('No message text. Put it in "text" (or "content", as Discord does).')
    if author_obj is not None:
        author = _text_field(author_obj.get("global_name") or author_obj.get("username"), 120)
    else:
        author = _text_field(body.get("from") or body.get("author") or body.get("user") or body.get("username"), 120)
    author = author or _text_field(requester.get("name") or requester.get("email"), 120)
    default_source = "discord" if author_obj is not None else "support" if ticket else "other"
    return InboxMessage(
        text=text,
        source=source_key(body.get("source") or default_source),
        author=author,
        customer=_text_field(body.get("customer") or body.get("account") or body.get("customer_id"), 200),
        plan=_text_field(body.get("plan") or body.get("tier"), 40),
        arr=_number(body.get("arr")),
        external_id=_text_field(body.get("id") or body.get("external_id") or ticket.get("id"), 200),
        occurred_at=_event_time(body.get("occurred_at") or body.get("timestamp") or ticket.get("created_at")),
    )


def quote_of(clean: str) -> str:
    """The start of the message, word for word (cut at a space, no ellipsis, so it stays a verbatim quote)."""
    if len(clean) <= QUOTE_CHARS:
        return clean
    cut = clean[:QUOTE_CHARS]
    return cut[: cut.rfind(" ")] if " " in cut else cut


# ---------------------------------------------------------------- the model

_model_lock = threading.Lock()
_warming: Optional["asyncio.Task[None]"] = None
_warm_failed = False


def _load_model() -> None:
    with _model_lock:
        embeddings.get_embedding_model()


def embed_message(text: str) -> List[float]:
    """Same model and normalisation as the pipeline (embeddings.embed_texts)."""
    _load_model()
    return embeddings.embed_texts([text])[0]


def warm_model() -> None:
    """Load the model in the background when someone opens the inbox, so the first message isn't slow."""
    global _warming
    if embeddings._model_instance is not None or _warm_failed or (_warming is not None and not _warming.done()):
        return

    async def _run() -> None:
        global _warm_failed
        try:
            await asyncio.to_thread(_load_model)
        except Exception as e:  # the message itself will report the problem
            _warm_failed = True
            logger.warning(f"Could not preload the embedding model: {e}")

    _warming = asyncio.get_running_loop().create_task(_run())


# ---------------------------------------------------------------- webhook links

TOKEN_PREFIX = "motif_in_"
_hook_hits: Dict[str, Deque[float]] = {}


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(24)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def allow_hook(key: str, limit: int = HOOK_LIMIT_PER_MINUTE) -> bool:
    """At most `limit` messages a minute per webhook link (in memory, per server process)."""
    now = time.monotonic()
    hits = _hook_hits.setdefault(key, deque())
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True


# ---------------------------------------------------------------- matching

async def _closest_themes(db: AsyncSession, vector: List[float], theme_ids: List[Any], limit: int = 3) -> List[Tuple[Any, float]]:
    """For each theme, the similarity of its most similar message to the new one (pgvector), best first."""
    distance = func.min(FeedbackItem.embedding.cosine_distance(vector))
    rows = (await db.execute(
        select(theme_feedback_associations.c.theme_id, distance.label("distance"))
        .join(FeedbackItem, FeedbackItem.id == theme_feedback_associations.c.feedback_item_id)
        .where(theme_feedback_associations.c.theme_id.in_(theme_ids), FeedbackItem.embedding.isnot(None))
        .group_by(theme_feedback_associations.c.theme_id)
        .order_by(distance)
        .limit(limit)
    )).all()
    return [(row.theme_id, round(1.0 - float(row.distance), 4)) for row in rows]


async def _closest_message(db: AsyncSession, vector: List[float], theme_id: Any) -> Optional[str]:
    content = await db.scalar(
        select(FeedbackItem.content)
        .join(theme_feedback_associations, theme_feedback_associations.c.feedback_item_id == FeedbackItem.id)
        .where(theme_feedback_associations.c.theme_id == theme_id, FeedbackItem.embedding.isnot(None))
        .order_by(FeedbackItem.embedding.cosine_distance(vector))
        .limit(1)
    )
    return " ".join((content or "").split())[:300] or None


async def _known_customer(db: AsyncSession, project_id: Optional[str], customer: str) -> Optional[Tuple[str, float, str]]:
    """The customer as already recorded in this project: their spelling, largest ARR and tier."""
    row = (await db.execute(
        select(FeedbackItem.customer_id, FeedbackItem.arr_value, FeedbackItem.customer_tier)
        .where(in_scope(FeedbackItem.project_id, project_id), func.lower(FeedbackItem.customer_id) == customer.lower())
        .order_by(FeedbackItem.arr_value.desc().nulls_last())
        .limit(1)
    )).first()
    if row is None:
        return None
    return row.customer_id, float(row.arr_value or 0.0), (row.customer_tier or "free")


def _signal_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    old = {s["key"]: s for s in before.get("signals", [])}
    changes = []
    for signal in after.get("signals", []):
        prev = old.get(signal["key"])
        if prev is None or prev["value"] != signal["value"] or prev["points"] != signal["points"]:
            changes.append({
                "key": signal["key"], "label": signal["label"],
                "value_before": prev["value"] if prev else None, "value_after": signal["value"],
                "points_before": prev["points"] if prev else 0.0, "points_after": signal["points"],
            })
    return changes


def feed_entry(item: FeedbackItem, now_in: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = item.metadata_ or {}
    return {
        "id": str(item.id),
        "text": (item.content or "")[:1000],
        "author": item.speaker,
        "customer": item.customer_id,
        "source": meta.get("source_name"),
        "via": meta.get("via"),
        "received_at": meta.get("received_at") or (item.created_at.isoformat() if item.created_at else None),
        "received_by": meta.get("received_by"),
        "churn": bool(item.churn_risk_flag),
        "arr": float(item.arr_value or 0.0),
        "arr_from": meta.get("arr_from"),
        "match": meta.get("match") or {},
        "now_in": now_in,
    }


async def _save(db: AsyncSession, item: FeedbackItem, meta: Dict[str, Any], match: Dict[str, Any]) -> Dict[str, Any]:
    item.metadata_ = {**meta, "match": match}
    db.add(item)
    await db.commit()
    return feed_entry(item)


async def receive(
    db: AsyncSession,
    project_id: Optional[str],
    message: InboxMessage,
    via: str,
    received_by: Optional[str] = None,
    analysis_running: bool = False,
) -> Dict[str, Any]:
    """Store one live message, join it to a theme if it is similar enough, and re-score. Commits."""
    content = (message.text or "").strip()
    if len(content) > MAX_TEXT_CHARS:
        raise InboxError(f"That message is {len(content):,} characters. Send at most {MAX_TEXT_CHARS:,}.")
    clean = clean_text(content)
    if len(clean) < 3:
        raise InboxError("The message is empty once links and markup are removed.")

    if message.external_id:  # a webhook sending the same message again
        existing = await db.scalar(
            select(FeedbackItem).options(defer(FeedbackItem.embedding)).where(
                in_scope(FeedbackItem.project_id, project_id),
                FeedbackItem.external_id == message.external_id,
                FeedbackItem.metadata_["live"].astext == "true",
            ).limit(1)
        )
        if existing is not None:
            return {**feed_entry(existing), "duplicate": True}

    customer, tier, arr, arr_from = message.customer, "free", 0.0, None
    known = await _known_customer(db, project_id, message.customer) if message.customer else None
    if known:
        customer, arr, tier = known
        arr_from = "this customer's existing records" if arr > 0 else None
    plan = (message.plan or "").lower()
    if plan in TIERS:
        tier = plan
    if message.arr is not None:
        arr, arr_from = message.arr, "sent with the message"

    vector = await asyncio.to_thread(embed_message, clean)
    now = datetime.now(timezone.utc)
    label = SOURCES.get(message.source, "Other")
    meta: Dict[str, Any] = {"live": True, "via": via, "source_name": label, "received_at": now.isoformat()}
    if received_by:
        meta["received_by"] = received_by
    if message.occurred_at:
        meta["occurred_at"] = message.occurred_at
    if arr_from:
        meta["arr_from"] = arr_from
    item = FeedbackItem(
        id=uuid.uuid4(), project_id=project_id, source_type=message.source, external_id=message.external_id,
        content=content, clean_content=clean, customer_id=customer, customer_tier=tier, arr_value=arr,
        churn_risk_flag=detect_churn_intent(clean), embedding=vector, speaker=message.author, created_at=now,
    )

    if analysis_running:
        return await _save(db, item, meta, {"status": "waiting", "reason": "The project is being analysed right now. This message will be grouped on the next Analyze."})

    peers = await scoring_peers(db, project_id)
    candidates = [p for p in peers if p.status != "rejected"]
    if not candidates:
        return await _save(db, item, meta, {"status": "waiting", "reason": "No themes yet. Analyze the project first; after that, new messages join themes as they arrive."})

    by_id = {p.id: p for p in peers}
    closest = await _closest_themes(db, vector, [p.id for p in candidates])
    options = [{"theme_id": str(tid), "title": by_id[tid].title, "similarity": sim, "status": by_id[tid].status} for tid, sim in closest]
    threshold = match_threshold()
    if not closest or closest[0][1] < threshold:
        nearest = options[0] if options else None
        reason = "Not similar enough to any theme"
        if nearest:
            reason += f": the closest is “{nearest['title']}” at {round(nearest['similarity'] * 100)}% and a theme needs {round(threshold * 100)}%"
        reason += ". It will be grouped on the next Analyze, maybe as a new theme."
        return await _save(db, item, meta, {"status": "waiting", "reason": reason, "closest": options, "threshold": threshold})

    theme = by_id[closest[0][0]]
    index = next(i for i, p in enumerate(peers) if p.id == theme.id)
    closest_text = await _closest_message(db, vector, theme.id)
    profile = profile_of(peers)
    sources_before = await source_names(db, project_id)
    inputs = await theme_inputs(db, peers, project_id)
    previous = snapshot(peers)
    before = rescore(inputs, previous, profile, len(sources_before))

    db.add(item)
    await db.flush()
    await db.execute(theme_feedback_associations.insert().values(
        theme_id=theme.id, feedback_item_id=item.id, is_cited_quote=True, quote_text=quote_of(clean),
    ))
    after_inputs = [dict(entry, items=list(entry["items"])) for entry in inputs]
    after_inputs[index]["items"].append(scoring_item(item, project_id))
    after_inputs[index]["verified_quotes"] += 1  # the message itself, quoted word for word
    after = rescore(after_inputs, previous, profile, len(sources_before | {label}))

    for peer, breakdown in zip(peers, after):
        peer.score_breakdown = breakdown
        peer.priority_score = breakdown["priority_score"]
        flag_modified(peer, "score_breakdown")
    risk = calculate_revenue_at_risk(after_inputs[index]["items"], cohesion_score=after_inputs[index]["cohesion"] or 1.0)
    theme.revenue_at_risk = risk["revenue_at_risk"]
    theme.affected_accounts_count = risk["affected_accounts_count"]

    moved = [
        {"theme_id": str(p.id), "title": p.title, "status": p.status, "from": b["rank"], "to": a["rank"]}
        for p, b, a in zip(peers, before, after) if b["rank"] != a["rank"]
    ]
    newly_used = sorted({d["label"] for d in before[index].get("dropped", [])} - {d["label"] for d in after[index].get("dropped", [])})
    match = {
        "status": "joined",
        "theme_id": str(theme.id),
        "theme_title": theme.title,
        "theme_status": theme.status,
        "github_issue_url": theme.github_issue_url,
        "similarity": closest[0][1],
        "threshold": threshold,
        "closest_text": closest_text,
        "closest": options,
        "rank_before": before[index]["rank"],
        "rank_after": after[index]["rank"],
        "of": after[index]["of"],
        "score_before": before[index]["priority_score"],
        "score_after": after[index]["priority_score"],
        "lane": after[index].get("lane"),
        "type_before": (before[index].get("issue_type") or {}).get("label"),
        "type_after": (after[index].get("issue_type") or {}).get("label"),
        "signals": _signal_changes(before[index], after[index]),
        "newly_used": newly_used,
        "moved": moved[:12],
    }
    item.metadata_ = {**meta, "match": match}
    await db.commit()
    return feed_entry(item, now_in={"theme_id": str(theme.id), "title": theme.title, "status": theme.status})


async def feed(db: AsyncSession, project_id: Optional[str], limit: int = FEED_LIMIT) -> List[Dict[str, Any]]:
    """The newest live messages, each with the theme it is in now (after a re-analysis it may have moved)."""
    items = (await db.scalars(
        select(FeedbackItem).options(defer(FeedbackItem.embedding))
        .where(in_scope(FeedbackItem.project_id, project_id), FeedbackItem.metadata_["live"].astext == "true")
        .order_by(FeedbackItem.created_at.desc())
        .limit(limit)
    )).all()
    if not items:
        return []
    rows = (await db.execute(
        select(theme_feedback_associations.c.feedback_item_id, Theme.id, Theme.title, Theme.status, Theme.created_at)
        .join(Theme, Theme.id == theme_feedback_associations.c.theme_id)
        .where(theme_feedback_associations.c.feedback_item_id.in_([i.id for i in items]), Theme.status != "rejected")
        .order_by(Theme.created_at.desc())
    )).all()
    now_in: Dict[Any, Dict[str, Any]] = {}
    for row in rows:  # newest theme first: the latest analysis wins
        now_in.setdefault(row.feedback_item_id, {"theme_id": str(row.id), "title": row.title, "status": row.status})
    return [feed_entry(item, now_in.get(item.id)) for item in items]
