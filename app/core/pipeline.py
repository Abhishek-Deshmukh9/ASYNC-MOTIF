import logging
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


async def run_ai_pipeline(
    batch_size: int = 50,
    min_cluster_size: int = 4,
    min_samples: int = 2,
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

    # Step 1: Embed any un-embedded feedback items
    embedded_count = await embed_all_unembedded_items(batch_size=batch_size)
    logger.info(f"Step 1 Complete: {embedded_count} feedback items embedded.")

    # Step 2: Fetch all embedded feedback items for clustering
    async with AsyncSessionLocal() as session:
        query = select(FeedbackItem).where(FeedbackItem.embedding.isnot(None))
        result = await session.execute(query)
        db_items = result.scalars().all()

        if not db_items:
            return {
                "status": "completed",
                "message": "No feedback items with embeddings found in database.",
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

    # Step 3: HDBSCAN Density Clustering
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

    # Step 4: Synthesize Themes & Compute Revenue-at-Risk
    created_themes: List[Dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        # Clear existing unapproved themes if re-running
        await session.execute(
            delete(Theme).where(Theme.status == "pending_review")
        )
        await session.commit()

        for cluster_id, c_items in cluster_res.clusters.items():
            cohesion = cluster_res.cohesion_scores.get(cluster_id, 1.0)
            exemplars = cluster_res.exemplars.get(cluster_id, c_items[:5])

            # LLM Theme Synthesis with Quote Grounding
            synthesized = await synthesize_cluster_theme(c_items, exemplars=exemplars)

            # Revenue at Risk Ranking
            risk_metrics = calculate_revenue_at_risk(c_items, cohesion_score=cohesion)

            theme_id = uuid.uuid4()
            theme_record = Theme(
                id=theme_id,
                cluster_id=cluster_id,
                title=synthesized.title,
                summary=synthesized.problem_statement,
                revenue_at_risk=risk_metrics["revenue_at_risk"],
                affected_accounts_count=risk_metrics["affected_accounts_count"],
                status="pending_review",
            )
            session.add(theme_record)
            await session.flush()

            # Associate feedback items and flag cited quotes
            for c_item in c_items:
                # Check if this item matches any cited quote
                item_text = (c_item.get("content") or "") + (c_item.get("clean_content") or "")
                matched_quote = None
                for q in synthesized.cited_quotes:
                    if q in item_text:
                        matched_quote = q
                        break

                await session.execute(
                    theme_feedback_associations.insert().values(
                        theme_id=theme_id,
                        feedback_item_id=c_item["id"],
                        is_cited_quote=(matched_quote is not None),
                        quote_text=matched_quote,
                    )
                )

            created_themes.append({
                "theme_id": str(theme_id),
                "cluster_id": cluster_id,
                "title": synthesized.title,
                "revenue_at_risk": risk_metrics["revenue_at_risk"],
                "affected_accounts": risk_metrics["affected_accounts_count"],
                "cited_quotes": synthesized.cited_quotes,
            })

        await session.commit()

    # Sort themes by revenue at risk descending
    created_themes.sort(key=lambda x: x["revenue_at_risk"], reverse=True)

    logger.info(f">>> Motif AI Pipeline Finished: {len(created_themes)} themes created and persisted. <<<")

    return {
        "status": "completed",
        "items_processed": len(items_for_clustering),
        "newly_embedded": embedded_count,
        "dense_clusters_count": cluster_res.total_dense_clusters,
        "noise_items_isolated": cluster_res.total_noise_count,
        "themes_created": len(created_themes),
        "themes": created_themes,
    }
