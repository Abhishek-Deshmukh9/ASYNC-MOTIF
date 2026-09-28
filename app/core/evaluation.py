"""
Benchmark evaluation for the demo corpus.

These functions are pure (no database access) so they can be unit-tested.
The /metrics/eval endpoint gathers rows from the database and passes them in.

Ground truth comes from the `ground_truth_theme` label that seed.py writes into
each feedback item's metadata. The label is never passed to the embedding,
clustering or LLM steps, so it cannot leak into the results it is used to grade.
"""
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.citation_verifier import verify_quote_against_pool
from app.core.ranker import calculate_revenue_at_risk

GROUND_TRUTH_KEY = "ground_truth_theme"


def ground_truth_top_k(items: Iterable[Dict[str, Any]], k: int = 3) -> List[str]:
    """
    The "human reviewer's top k": group labelled feedback by its ground-truth
    theme and rank the groups with the same revenue-at-risk formula the
    pipeline uses. Items without a label are ignored.
    """
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        label = item.get(GROUND_TRUTH_KEY)
        if label:
            groups[label].append(item)

    ranked = sorted(
        groups.items(),
        key=lambda kv: calculate_revenue_at_risk(kv[1])["revenue_at_risk"],
        reverse=True,
    )
    return [label for label, _ in ranked[:k]]


def dominant_label(member_labels: Iterable[Optional[str]]) -> Tuple[Optional[str], float]:
    """Most common ground-truth label among a theme's members, and its share (purity)."""
    labels = [label for label in member_labels if label]
    if not labels:
        return None, 0.0
    label, count = Counter(labels).most_common(1)[0]
    return label, count / len(labels)


def precision_at_k(
    discovered_top_labels: List[Optional[str]],
    ground_truth_top: List[str],
    k: int = 3,
) -> Optional[float]:
    """
    Share of the top-k discovered themes that match a distinct ground-truth
    top-k theme. Two discovered themes that are really the same problem only
    count once, so splitting one issue into duplicates is penalised.
    Returns None when there is nothing to compare yet.
    """
    if not discovered_top_labels or not ground_truth_top:
        return None

    matched = set()
    for label in discovered_top_labels[:k]:
        if label in ground_truth_top[:k]:
            matched.add(label)
    return round(len(matched) / k * 100, 1)


def citation_validity(quote_rows: Iterable[Tuple[Optional[str], str]]) -> Tuple[Optional[float], int, int]:
    """
    Re-checks every stored quote against the text of the feedback item it is
    attached to. quote_rows: (quote_text, source_text) pairs.
    Returns (percentage or None if there are no quotes, verified count, total count).
    """
    total = 0
    verified = 0
    for quote, source_text in quote_rows:
        if not quote:
            continue
        total += 1
        if verify_quote_against_pool(quote, [source_text or ""]):
            verified += 1
    if total == 0:
        return None, 0, 0
    return round(verified / total * 100, 1), verified, total


def acceptance_rate(unedited_approvals: int, total_decisions: int) -> Optional[float]:
    """Share of PM decisions that approved a theme without editing it. None before any decision."""
    if total_decisions <= 0:
        return None
    return round(unedited_approvals / total_decisions * 100, 1)
