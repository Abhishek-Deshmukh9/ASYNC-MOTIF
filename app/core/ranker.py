import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Urgency multipliers for churn intent (FR-4.3)
CHURN_URGENCY_WEIGHT = 2.5
STANDARD_URGENCY_WEIGHT = 1.0


def calculate_revenue_at_risk(
    items: List[Dict[str, Any]],
    cohesion_score: float = 1.0,
) -> Dict[str, Any]:
    """
    Computes theme financial priority score (FR-4.1):
    Score = sum(Account ARR * Churn Intent Weight) * Cluster Cohesion Score
    """
    total_raw_arr = 0.0
    weighted_score = 0.0
    affected_accounts = set()

    for item in items:
        arr = float(item.get("arr_value", 0.0))
        is_churn = bool(item.get("churn_risk_flag", False))
        customer_id = item.get("customer_id")

        if customer_id:
            affected_accounts.add(customer_id)

        weight = CHURN_URGENCY_WEIGHT if is_churn else STANDARD_URGENCY_WEIGHT
        total_raw_arr += arr
        weighted_score += (arr * weight)

    # Scale with cluster cohesion (normalized between 0.5 and 1.5)
    clamped_cohesion = max(0.5, min(1.5, cohesion_score))
    final_priority_score = round(weighted_score * clamped_cohesion, 2)

    return {
        "revenue_at_risk": round(total_raw_arr, 2),
        "priority_score": final_priority_score,
        "affected_accounts_count": len(affected_accounts),
    }
