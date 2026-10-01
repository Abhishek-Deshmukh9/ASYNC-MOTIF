"""
Re-score a project's themes from what is stored, with the same arithmetic as the pipeline.

Used when the data behind a ranking changes without a full re-analysis: a PM changes a theme's kind of problem,
or a live message joins a theme. The ranking set is the themes of the latest analysis ("peers"), so themes left
over from older runs (already approved, say) don't change the numbers on screen.
"""
import copy
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pipeline import scoring_item
from app.core.scoring import DEFAULT_PROFILE, retype_breakdowns, score_themes
from app.models.feedback import FeedbackItem, theme_feedback_associations
from app.models.theme import Theme


def in_scope(column, project_id: Optional[str]):
    """A project's rows, or the shared demo corpus (project_id None)."""
    return column == project_id if project_id is not None else column.is_(None)


async def scoring_peers(db: AsyncSession, project_id: Optional[str], lock: bool = True) -> List[Theme]:
    """
    The themes ranked together: those of the latest analysis (same run_id), or every scored theme for data
    analysed before run ids were stored. Locked by default, so two changes at once are applied in turn.
    """
    scope = in_scope(Theme.project_id, project_id)
    run_id = Theme.score_breakdown["run_id"].astext
    latest = await db.scalar(
        select(run_id).where(scope, run_id.isnot(None)).order_by(Theme.created_at.desc()).limit(1)
    )
    query = select(Theme).where(scope, Theme.score_breakdown.isnot(None))
    if latest:
        query = query.where(run_id == latest)
    query = query.order_by(Theme.id)
    if lock:
        query = query.with_for_update()
    return list((await db.scalars(query)).all())


async def theme_inputs(db: AsyncSession, peers: List[Theme], project_id: Optional[str]) -> List[Dict[str, Any]]:
    """Each peer's messages (as the pipeline reads them), with the cohesion and verified quotes stored at analysis."""
    rows = (await db.execute(
        select(theme_feedback_associations.c.theme_id, FeedbackItem)
        .join(FeedbackItem, FeedbackItem.id == theme_feedback_associations.c.feedback_item_id)
        .where(theme_feedback_associations.c.theme_id.in_([p.id for p in peers]))
        .order_by(FeedbackItem.created_at, FeedbackItem.id)
    )).all()
    by_theme: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for theme_id, item in rows:
        by_theme[theme_id].append(scoring_item(item, project_id))
    inputs = []
    for peer in peers:
        confidence = (peer.score_breakdown or {}).get("confidence") or {}
        inputs.append({
            "items": by_theme[peer.id],
            "cohesion": float(confidence.get("cohesion", 0.0) or 0.0),
            "verified_quotes": int(confidence.get("verified_quotes", 0) or 0),
        })
    return inputs


async def source_names(db: AsyncSession, project_id: Optional[str]) -> Set[str]:
    """Distinct sources across the project's analysed messages (what the pipeline counts for source spread)."""
    name = func.coalesce(func.nullif(FeedbackItem.metadata_["source_name"].astext, ""), FeedbackItem.source_type)
    rows = await db.scalars(
        select(func.distinct(name)).where(in_scope(FeedbackItem.project_id, project_id), FeedbackItem.embedding.isnot(None))
    )
    return {r for r in rows if r}


def profile_of(peers: List[Theme]) -> str:
    return next(((p.score_breakdown or {}).get("profile") for p in peers if (p.score_breakdown or {}).get("profile")), DEFAULT_PROFILE)


def rescore(inputs: List[Dict[str, Any]], previous: List[Dict[str, Any]], profile: str, source_count: int) -> List[Dict[str, Any]]:
    """Score every peer again; a kind of problem set by a PM is kept, and so is the analysis run id."""
    results = score_themes(inputs, profile=profile, project_source_count=source_count)
    for index, old in enumerate(previous):
        issue = (old or {}).get("issue_type") or {}
        if issue.get("source") == "pm" and issue.get("type"):
            retype_breakdowns(results, index, issue["type"])
    for old, new in zip(previous, results):
        if (old or {}).get("run_id"):
            new["run_id"] = old["run_id"]
    return results


def snapshot(peers: List[Theme]) -> List[Dict[str, Any]]:
    return [copy.deepcopy(p.score_breakdown) for p in peers]
