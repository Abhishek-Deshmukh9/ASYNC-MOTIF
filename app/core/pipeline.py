import asyncio
from datetime import datetime, timezone
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.feedback import FeedbackItem, theme_feedback_associations
from app.models.theme import Theme
from app.core.embeddings import embed_all_unembedded_items
from app.core.clustering import cluster_feedback_embeddings, ClusterResult
from app.core.llm_labeler import synthesize_cluster_theme
from app.core.ranker import calculate_revenue_at_risk
from app.core.scoring import DEFAULT_PROFILE, score_themes

logger = logging.getLogger(__name__)

# progress(stage, done, total): stage is embedding | clustering | labelling | saving
Progress = Callable[[str, int, int], None]


def _event_date(item: Any, project_id: Optional[str]) -> Optional[datetime]:
    meta = item.metadata_ or {}
    raw = meta.get("occurred_at")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if meta.get("live"):
        return None  # when a message reached the live inbox is not when it happened, like upload time
    return item.created_at if project_id is None else None


def scoring_item(item: Any, project_id: Optional[str]) -> Dict[str, Any]:
    """The fields of one stored message that clustering and scoring read."""
    return {
        "id": item.id,
        "content": item.content,
        "clean_content": item.clean_content,
        "customer_id": item.customer_id,
        "customer_tier": item.customer_tier,
        "arr_value": float(item.arr_value or 0.0),
        "churn_risk_flag": bool(item.churn_risk_flag),
        "source_type": item.source_type,
        "source_name": (item.metadata_ or {}).get("source_name"),
        "speaker": item.speaker,
        "source_id": str(item.source_id) if item.source_id else None,
        # Real event date: carried in metadata by connectors; the seeded demo corpus stores it in created_at.
        # Upload time is not an event date, so projects without a carried date get none.
        "occurred_at": _event_date(item, project_id),
        "embedding": item.embedding,
    }


def _verified_count(items: List[Dict[str, Any]], quotes: List[str]) -> int:
    """Messages in the theme that contain one of its quotes word for word: the same count the theme card shows."""
    return sum(
        1 for it in items
        if any(q and q in (it.get("content") or "") + (it.get("clean_content") or "") for q in quotes)
    )


async def run_ai_pipeline(
    batch_size: int = 50,
    min_cluster_size: int = 4,
    min_samples: int = 2,
    project_id: Optional[str] = None,
    progress: Optional[Progress] = None,
    profile: str = DEFAULT_PROFILE,
) -> Dict[str, Any]:
    """
    Executes Phase 3 Core AI Processing:
    1. Embed un-embedded feedback items in batches using sentence-transformers (MiniLM-L6-v2).
    2. Run HDBSCAN unsupervised density clustering, isolating noise.
    3. Synthesize structured themes via LLM (Gemini Flash/Groq/OpenAI) with grounded quote citations.
    4. Deterministically verify citations against source texts (Rule 1.1).
    5. Compute Revenue-at-Risk scoring and persist themes & associations.
    """
    logger.info(">>> Starting Motif AI Pipeline (Phase 3) <<<")
    started_at = time.perf_counter()
    batch_size = batch_size or 50
    min_cluster_size = min_cluster_size or 4
    min_samples = min_samples or 2

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    # Step 1: Embed any un-embedded feedback items
    report("embedding")
    embedded_count = await embed_all_unembedded_items(batch_size=batch_size)
    logger.info(f"Step 1 Complete: {embedded_count} feedback items embedded.")

    # Step 2: Fetch all embedded feedback items for clustering
    async with AsyncSessionLocal() as session:
        query = select(FeedbackItem).where(FeedbackItem.embedding.isnot(None))
        # Each run covers exactly one scope: a project, or (project_id=None) the unscoped
        # demo corpus loaded by seed.py. This matches how pending themes are cleared below.
        if project_id is not None:
            query = query.where(FeedbackItem.project_id == project_id)
        else:
            query = query.where(FeedbackItem.project_id.is_(None))
        result = await session.execute(query)
        db_items = result.scalars().all()

        if not db_items:
            return {
                "status": "completed",
                "message": "No feedback items with embeddings found in database.",
                "project_id": project_id,
                "duration_seconds": round(time.perf_counter() - started_at, 1),
                "items_processed": 0,
                "themes_created": 0,
                "noise_count": 0,
            }

        items_for_clustering = [scoring_item(item, project_id) for item in db_items]

    # Step 3: HDBSCAN Density Clustering
    report("clustering", 0, len(items_for_clustering))
    logger.info(f"Step 2: Clustering {len(items_for_clustering)} items with HDBSCAN...")
    cluster_res: ClusterResult = cluster_feedback_embeddings(
        items_for_clustering,
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
    )

    logger.info(
        f"Clustering output: {cluster_res.total_dense_clusters} dense clusters, "
        f"{cluster_res.total_noise_count} noise items."
    )

    # Step 4: Synthesize Themes Concurrently (avoiding long DB session locks)
    logger.info(f"Step 3: Synthesizing themes for {len(cluster_res.clusters)} clusters concurrently...")
    semaphore = asyncio.Semaphore(3)
    total_clusters = len(cluster_res.clusters)
    finished = 0
    report("labelling", 0, total_clusters)

    async def _process_cluster(cluster_id: int, c_items: List[Dict[str, Any]]):
        async with semaphore:
            cohesion = cluster_res.cohesion_scores.get(cluster_id, 1.0)
            exemplars = cluster_res.exemplars.get(cluster_id, c_items[:5])
            try:
                synthesized = await synthesize_cluster_theme(c_items, exemplars=exemplars)
            except Exception as e:
                logger.error(f"Cluster {cluster_id} theme synthesis failed ({e}), using fallback.")
                from app.core.llm_labeler import _synthesize_offline_grounded_theme
                source_texts = [it.get("content", "") for it in c_items] + [it.get("clean_content", "") for it in c_items]
                synthesized = _synthesize_offline_grounded_theme(exemplars, source_texts)
            risk_metrics = calculate_revenue_at_risk(c_items, cohesion_score=cohesion)
            nonlocal finished
            finished += 1
            report("labelling", finished, total_clusters)
            return cluster_id, c_items, synthesized, risk_metrics

    tasks = [
        _process_cluster(cid, c_items)
        for cid, c_items in cluster_res.clusters.items()
    ]
    cluster_payloads = await asyncio.gather(*tasks)

    # Transparent ranking: every theme gets a priority score plus the signals, evidence and reasons behind it
    all_sources = {s for it in items_for_clustering for s in [it.get("source_name") or it.get("source_type")] if s}
    breakdowns = score_themes(
        [
            {
                "items": c_items,
                "cohesion": cluster_res.cohesion_scores.get(cluster_id, 1.0),
                "verified_quotes": _verified_count(c_items, synthesized.cited_quotes),
            }
            for cluster_id, c_items, synthesized, _ in cluster_payloads
        ],
        profile=profile,
        project_source_count=len(all_sources),
    )
    # Themes ranked together share a run id, so later re-scoring (a type change, a live message) uses the same set
    run_id = str(uuid.uuid4())
    for breakdown in breakdowns:
        breakdown["run_id"] = run_id
    breakdown_by_cluster = {payload[0]: breakdowns[i] for i, payload in enumerate(cluster_payloads)}

    # Step 5: Fast atomic persistence to database
    report("saving", total_clusters, total_clusters)
    created_themes: List[Dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        # Clear existing unapproved themes if re-running
        pending_query = delete(Theme).where(Theme.status == "pending_review")
        if project_id is None:
            pending_query = pending_query.where(Theme.project_id.is_(None))
        else:
            pending_query = pending_query.where(Theme.project_id == project_id)
        await session.execute(pending_query)

        theme_id_map: Dict[int, uuid.UUID] = {}
        for cluster_id, c_items, synthesized, risk_metrics in cluster_payloads:
            theme_id = uuid.uuid4()
            theme_record = Theme(
                id=theme_id,
                cluster_id=cluster_id,
                project_id=project_id,
                title=synthesized.title,
                summary=synthesized.problem_statement,
                revenue_at_risk=risk_metrics["revenue_at_risk"],
                affected_accounts_count=risk_metrics["affected_accounts_count"],
                priority_score=breakdown_by_cluster[cluster_id]["priority_score"],
                score_breakdown=breakdown_by_cluster[cluster_id],
                status="pending_review",
            )
            session.add(theme_record)
            theme_id_map[cluster_id] = theme_id

        # Flush all themes to database so foreign key constraint is satisfied
        await session.flush()

        # Collect all association rows and batch insert in a single query
        assoc_rows: List[Dict[str, Any]] = []
        for cluster_id, c_items, synthesized, risk_metrics in cluster_payloads:
            theme_id = theme_id_map[cluster_id]
            for c_item in c_items:
                item_text = (c_item.get("content") or "") + (c_item.get("clean_content") or "")
                matched_quote = None
                for q in synthesized.cited_quotes:
                    if q in item_text:
                        matched_quote = q
                        break

                assoc_rows.append({
                    "theme_id": theme_id,
                    "feedback_item_id": c_item["id"],
                    "is_cited_quote": (matched_quote is not None),
                    "quote_text": matched_quote,
                })

            created_themes.append({
                "theme_id": str(theme_id),
                "cluster_id": cluster_id,
                "title": synthesized.title,
                "revenue_at_risk": risk_metrics["revenue_at_risk"],
                "priority_score": breakdown_by_cluster[cluster_id]["priority_score"],
                "affected_accounts": risk_metrics["affected_accounts_count"],
                "cited_quotes": synthesized.cited_quotes,
            })

        if assoc_rows:
            await session.execute(theme_feedback_associations.insert(), assoc_rows)

        await session.commit()

    # Sort themes by priority score, then revenue at risk
    created_themes.sort(key=lambda x: (x["priority_score"], x["revenue_at_risk"]), reverse=True)

    logger.info(f">>> Motif AI Pipeline Finished: {len(created_themes)} themes created and persisted. <<<")

    duration_seconds = round(time.perf_counter() - started_at, 1)
    logger.info(f"Pipeline run took {duration_seconds}s end to end.")

    return {
        "status": "completed",
        "project_id": project_id,
        "duration_seconds": duration_seconds,
        "items_processed": len(items_for_clustering),
        "newly_embedded": embedded_count,
        "dense_clusters_count": cluster_res.total_dense_clusters,
        "noise_items_isolated": cluster_res.total_noise_count,
        "themes_created": len(created_themes),
        "themes": created_themes,
    }
