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

    ARR is counted once per account, not once per message: an account that
    complains 20 times still only has its own ARR at risk. If any of an
    account's messages carries churn intent, that account gets the churn weight.
    Items without a customer_id are treated as separate anonymous accounts.
    """
    accounts: Dict[str, Dict[str, Any]] = {}

    for idx, item in enumerate(items):
        arr = float(item.get("arr_value", 0.0) or 0.0)
        is_churn = bool(item.get("churn_risk_flag", False))
        key = item.get("customer_id") or f"__anonymous_{idx}"

        account = accounts.setdefault(key, {"arr": 0.0, "churn": False})
        account["arr"] = max(account["arr"], arr)
        account["churn"] = account["churn"] or is_churn

    total_raw_arr = sum(a["arr"] for a in accounts.values())
    weighted_score = sum(
        a["arr"] * (CHURN_URGENCY_WEIGHT if a["churn"] else STANDARD_URGENCY_WEIGHT)
        for a in accounts.values()
    )
    affected_accounts = [k for k in accounts if not k.startswith("__anonymous_")]

    # Scale with cluster cohesion (normalized between 0.5 and 1.5)
    clamped_cohesion = max(0.5, min(1.5, cohesion_score))
    final_priority_score = round(weighted_score * clamped_cohesion, 2)

    return {
        "revenue_at_risk": round(total_raw_arr, 2),
        "priority_score": final_priority_score,
        "affected_accounts_count": len(affected_accounts),
    }
