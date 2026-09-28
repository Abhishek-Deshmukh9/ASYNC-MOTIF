import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.api.deps import get_db
from app.models.theme import Theme
from app.models.audit import ApprovalAuditLog
from app.models.feedback import FeedbackItem, theme_feedback_associations
from app.core.evaluation import (
    GROUND_TRUTH_KEY,
    acceptance_rate as compute_acceptance_rate,
    citation_validity as compute_citation_validity,
    dominant_label,
    ground_truth_top_k,
    precision_at_k,
)
from app.core.ranker import calculate_revenue_at_risk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/eval", response_model=Dict[str, Any])
async def get_benchmark_metrics(db: AsyncSession = Depends(get_db)):
    """
    Live benchmark metrics, all computed from the database on every call:
    - Theme Precision @ 3 (P@3) against the seed corpus' ground-truth labels. Target >= 90%
    - PM Acceptance Rate (% of decisions that approved a theme without edits). Target >= 70%
    - Citation Validity (stored quotes re-verified against their source text). Target 100%
    - Total revenue at risk across open and approved themes (each account counted once)

    A metric is null when there is nothing to measure yet (e.g. no PM decisions).
    """
    # 1. Counts
    total_feedback = await db.scalar(select(func.count(FeedbackItem.id))) or 0
    total_themes = await db.scalar(select(func.count(Theme.id))) or 0
    approved_themes = await db.scalar(
        select(func.count(Theme.id)).where(Theme.status == "approved")
    ) or 0
    rejected_themes = await db.scalar(
        select(func.count(Theme.id)).where(Theme.status == "rejected")
    ) or 0
    pending_themes = await db.scalar(
        select(func.count(Theme.id)).where(Theme.status == "pending_review")
    ) or 0

    # 2. Theme membership: which feedback items (with ground-truth labels and ARR) belong to which theme
    member_rows = (
        await db.execute(
            select(
                theme_feedback_associations.c.theme_id,
                Theme.status,
                FeedbackItem.customer_id,
                FeedbackItem.arr_value,
                FeedbackItem.churn_risk_flag,
                FeedbackItem.metadata_,
            )
            .join(Theme, Theme.id == theme_feedback_associations.c.theme_id)
            .join(FeedbackItem, FeedbackItem.id == theme_feedback_associations.c.feedback_item_id)
        )
    ).all()

    labels_by_theme: Dict[Any, List[Optional[str]]] = defaultdict(list)
    open_theme_items: List[Dict[str, Any]] = []
    for row in member_rows:
        labels_by_theme[row.theme_id].append((row.metadata_ or {}).get(GROUND_TRUTH_KEY))
        if row.status != "rejected":
            open_theme_items.append(
                {
                    "customer_id": row.customer_id,
                    "arr_value": float(row.arr_value or 0.0),
                    "churn_risk_flag": bool(row.churn_risk_flag),
                }
            )

    # 3. Total ARR at risk: each account counted once, even if it appears in several themes
    total_arr_at_risk = calculate_revenue_at_risk(open_theme_items)["revenue_at_risk"]

    # 4. P@3 against ground truth
    labelled_items = [
        {
            "customer_id": r.customer_id,
            "arr_value": float(r.arr_value or 0.0),
            "churn_risk_flag": bool(r.churn_risk_flag),
            GROUND_TRUTH_KEY: (r.metadata_ or {}).get(GROUND_TRUTH_KEY),
        }
        for r in (
            await db.execute(
                select(
                    FeedbackItem.customer_id,
                    FeedbackItem.arr_value,
                    FeedbackItem.churn_risk_flag,
                    FeedbackItem.metadata_,
                )
            )
        ).all()
    ]
    gt_top_3 = ground_truth_top_k(labelled_items, k=3)

    # Top 3 discovered themes by revenue at risk. Themes with no feedback items left
    # (e.g. after the corpus was re-seeded) cannot be evaluated, so they are skipped.
    ranked_themes = (
        await db.execute(
            select(Theme.id, Theme.title).order_by(Theme.revenue_at_risk.desc())
        )
    ).all()
    top_3_themes = [(tid, title) for tid, title in ranked_themes if labels_by_theme.get(tid)][:3]
    top_3_breakdown = []
    discovered_labels: List[Optional[str]] = []
    for theme_id, title in top_3_themes:
        label, purity = dominant_label(labels_by_theme.get(theme_id, []))
        discovered_labels.append(label)
        top_3_breakdown.append(
            {
                "title": title,
                "matched_ground_truth_theme": label,
                "purity": round(purity * 100, 1),
                "is_in_ground_truth_top_3": label in gt_top_3,
            }
        )
    precision_at_3 = precision_at_k(discovered_labels, gt_top_3, k=3) if gt_top_3 else None

    # 5. Acceptance rate: final decisions (approve / reject) per theme, edits tracked separately
    audit_rows = (
        await db.execute(
            select(
                ApprovalAuditLog.theme_id,
                ApprovalAuditLog.action,
                ApprovalAuditLog.original_title,
                ApprovalAuditLog.final_title,
            )
        )
    ).all()
    edited_theme_ids = {r.theme_id for r in audit_rows if r.action == "edited"}
    decided_theme_ids = {r.theme_id for r in audit_rows if r.action in ("approved", "rejected")}
    unedited_approvals = {
        r.theme_id
        for r in audit_rows
        if r.action == "approved"
        and r.original_title == r.final_title
        and r.theme_id not in edited_theme_ids
    }
    acceptance_rate = compute_acceptance_rate(len(unedited_approvals), len(decided_theme_ids))

    # 6. Citation validity: re-verify every stored quote against its own source item
    quote_rows = (
        await db.execute(
            select(
                theme_feedback_associations.c.quote_text,
                FeedbackItem.content,
                FeedbackItem.clean_content,
            )
            .join(FeedbackItem, FeedbackItem.id == theme_feedback_associations.c.feedback_item_id)
            .where(theme_feedback_associations.c.is_cited_quote.is_(True))
        )
    ).all()
    citation_validity, verified_quotes, total_quotes = compute_citation_validity(
        (q, f"{content or ''}\n{clean or ''}") for q, content, clean in quote_rows
    )

    return {
        "precision_at_3": precision_at_3,
        "target_precision_at_3": 90.0,
        "ground_truth_top_3": gt_top_3,
        "top_3_breakdown": top_3_breakdown,
        "acceptance_rate": acceptance_rate,
        "target_acceptance_rate": 70.0,
        "pm_decisions_count": len(decided_theme_ids),
        "citation_validity": citation_validity,
        "target_citation_validity": 100.0,
        "verified_quotes_count": verified_quotes,
        "total_quotes_count": total_quotes,
        "total_feedback_items": total_feedback,
        "total_themes_discovered": total_themes,
        "approved_themes_count": approved_themes,
        "rejected_themes_count": rejected_themes,
        "pending_themes_count": pending_themes,
        "total_revenue_at_risk": float(total_arr_at_risk),
    }
