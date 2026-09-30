import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.feedback import FeedbackItem, theme_feedback_associations
from app.models.theme import Theme
from app.core.embeddings import embed_all_unembedded_items
from app.core.clustering import cluster_feedback_embeddings, ClusterResult
from app.core.llm_labeler import synthesize_cluster_theme
from app.core.ranker import calculate_revenue_at_risk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory pipeline progress tracker (single-worker safe)
# ---------------------------------------------------------------------------
class PipelineProgress:
    """Tracks stage-level progress for the running pipeline.
    
    Stages: idle → embedding → clustering → labeling → ranking → persisting → completed | failed
    """

    def __init__(self) -> None:
        self.status: str = "idle"
        self.stage: str = "idle"
        self.stage_detail: str = ""
        self.percent: int = 0
        self.started_at: Optional[float] = None
        self.last_result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self._subscribers: List[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def set(self, stage: str, detail: str = "", percent: int = 0) -> None:
        async with self._lock:
            self.stage = stage
            self.stage_detail = detail
            self.percent = percent
            await self._broadcast()

    async def _broadcast(self) -> None:
        msg = self.snapshot()
        dead: List[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def snapshot(self) -> Dict[str, Any]:
        elapsed = round(time.perf_counter() - self.started_at, 1) if self.started_at else None
        return {
            "status": self.status,
            "stage": self.stage,
            "stage_detail": self.stage_detail,
            "percent": self.percent,
            "elapsed_seconds": elapsed,
            "error": self.error,
            "last_result": self.last_result,
        }


pipeline_progress = PipelineProgress()


# ---------------------------------------------------------------------------
# Core Pipeline
# ---------------------------------------------------------------------------
async def run_ai_pipeline(
    batch_size: int = 50,
    min_cluster_size: int = 4,
    min_samples: int = 2,
    project_id: Optional[str] = None,
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
    pipeline_progress.started_at = started_at
    pipeline_progress.status = "running"
    pipeline_progress.error = None
    batch_size = batch_size or 50
    min_cluster_size = min_cluster_size or 4
    min_samples = min_samples or 2

    try:
        # Step 1: Embed any un-embedded feedback items
        await pipeline_progress.set("embedding", "Computing MiniLM-L6-v2 embeddings…", 10)
        embedded_count = await embed_all_unembedded_items(batch_size=batch_size)
        logger.info(f"Step 1 Complete: {embedded_count} feedback items embedded.")
        await pipeline_progress.set("embedding", f"{embedded_count} items embedded", 25)

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
                pipeline_progress.status = "idle"
                await pipeline_progress.set("idle", "No data", 100)
                return {
                    "status": "completed",
                    "message": "No feedback items with embeddings found in database.",
                    "project_id": project_id,
                    "duration_seconds": round(time.perf_counter() - started_at, 1),
                    "items_processed": 0,
                    "themes_created": 0,
                    "noise_count": 0,
                }

            items_for_clustering = [
                {
                    "id": item.id,
                    "content": item.content,
                    "clean_content": item.clean_content,
                    "customer_id": item.customer_id,
                    "customer_tier": item.customer_tier,
                    "arr_value": float(item.arr_value or 0.0),
                    "churn_risk_flag": bool(item.churn_risk_flag),
                    "source_type": item.source_type,
                    "embedding": item.embedding,
                }
                for item in db_items
            ]

        # Step 3: HDBSCAN Density Clustering (CPU-bound, offloaded to thread pool)
        await pipeline_progress.set("clustering", f"HDBSCAN on {len(items_for_clustering)} items…", 35)
        logger.info(f"Step 2: Clustering {len(items_for_clustering)} items with HDBSCAN...")
        loop = asyncio.get_event_loop()
        cluster_res: ClusterResult = await loop.run_in_executor(
            None,
            lambda: cluster_feedback_embeddings(
                items_for_clustering,
                min_cluster_size=min_cluster_size,
                min_samples=min_samples,
            ),
        )

        logger.info(
            f"Clustering output: {cluster_res.total_dense_clusters} dense clusters, "
            f"{cluster_res.total_noise_count} noise items."
        )
        await pipeline_progress.set(
            "clustering",
            f"{cluster_res.total_dense_clusters} clusters, {cluster_res.total_noise_count} noise",
            45,
        )

        # Step 4: Synthesize Themes Concurrently (avoiding long DB session locks)
        total_clusters = len(cluster_res.clusters)
        await pipeline_progress.set("labeling", f"Labeling {total_clusters} clusters with AI…", 50)
        logger.info(f"Step 3: Synthesizing themes for {total_clusters} clusters concurrently...")
        semaphore = asyncio.Semaphore(3)
        completed_labels = 0

        async def _process_cluster(cluster_id: int, c_items: List[Dict[str, Any]]):
            nonlocal completed_labels
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
                completed_labels += 1
                pct = 50 + int(35 * completed_labels / max(total_clusters, 1))
                await pipeline_progress.set(
                    "labeling",
                    f"{completed_labels}/{total_clusters} clusters labeled",
                    pct,
                )
                return cluster_id, c_items, synthesized, risk_metrics

        tasks = [
            _process_cluster(cid, c_items)
            for cid, c_items in cluster_res.clusters.items()
        ]
        cluster_payloads = await asyncio.gather(*tasks)

        # Step 5: Fast atomic persistence to database
        await pipeline_progress.set("persisting", "Saving themes to database…", 90)
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
                    "affected_accounts": risk_metrics["affected_accounts_count"],
                    "cited_quotes": synthesized.cited_quotes,
                })

            if assoc_rows:
                await session.execute(theme_feedback_associations.insert(), assoc_rows)

            await session.commit()

        # Sort themes by revenue at risk descending
        created_themes.sort(key=lambda x: x["revenue_at_risk"], reverse=True)

        duration_seconds = round(time.perf_counter() - started_at, 1)
        logger.info(f">>> Motif AI Pipeline Finished: {len(created_themes)} themes created and persisted. <<<")
        logger.info(f"Pipeline run took {duration_seconds}s end to end.")

        final_result = {
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

        pipeline_progress.last_result = final_result
        pipeline_progress.status = "idle"
        await pipeline_progress.set("completed", f"{len(created_themes)} themes created in {duration_seconds}s", 100)

        return final_result

    except Exception as e:
        pipeline_progress.status = "failed"
        pipeline_progress.error = str(e)
        await pipeline_progress.set("failed", str(e), 0)
        raise
