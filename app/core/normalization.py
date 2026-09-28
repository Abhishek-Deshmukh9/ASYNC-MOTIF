import re
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple
from app.connectors.base import RawFeedbackItem

# Default ARR values mapped to tiers if explicit ARR is missing (FR-4.2)
TIER_DEFAULT_ARR: Dict[str, float] = {
    "enterprise": 50000.0,
    "growth": 10000.0,
    "starter": 1000.0,
    "free": 0.0,
}

# High-urgency churn indicators (FR-4.3 & Rules 1.4)
CHURN_INDICATOR_KEYWORDS: List[str] = [
    "cancel",
    "cancelling",
    "cancellation",
    "switching to",
    "switched to",
    "unusable",
    "leaving",
    "churn",
    "alternative",
    "competitor",
    "breach of sla",
    "breach of contract",
    "refund",
    "blocker",
    "blocking our team",
    "waste of money",
]


def clean_text(text: str) -> str:
    """
    Standardize text: strip HTML script/style and markup, email signatures, redundant whitespace.
    """
    if not text:
        return ""

    # Remove script and style elements with their contents
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Strip markdown urls: [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    # Strip raw URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    # Remove space before punctuation
    cleaned = re.sub(r"\s+([.,!?;:])", r"\1", cleaned)
    # Normalize excessive newlines and whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def compute_lexical_fingerprint(text: str) -> str:
    """
    Generate SHA-256 hash of normalized lowercase alphanumeric string
    for exact duplicate detection.
    """
    normalized = re.sub(r"[^a-z0-9]", "", text.lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_similarity(text_a: str, text_b: str) -> float:
    """
    Compute token-level Jaccard similarity for near-duplicate detection.
    """
    tokens_a = set(re.findall(r"\w+", text_a.lower()))
    tokens_b = set(re.findall(r"\w+", text_b.lower()))

    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = len(tokens_a.intersection(tokens_b))
    union = len(tokens_a.union(tokens_b))

    return intersection / union


def detect_churn_intent(text: str) -> bool:
    """
    Scan normalized text for explicit churn risk markers.
    """
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in CHURN_INDICATOR_KEYWORDS)


def structure_customer_metadata(
    customer_id: Optional[str],
    customer_tier: Optional[str],
    arr_value: Optional[float],
    clean_content: str,
    fallback_fingerprint: str,
) -> Tuple[str, str, float, bool]:
    """
    Enforces customer metadata placeholders:
    - customer_id: fallback to anon_<hash> if unspecified.
    - customer_tier: standardized to 'enterprise', 'growth', 'starter', or 'free'.
    - arr_value: populated using tier default if 0 or None (FR-4.2).
    - churn_risk_flag: detected from churn keywords.
    """
    # 1. Standardize tier
    tier = (customer_tier or "free").lower().strip()
    if tier not in TIER_DEFAULT_ARR:
        tier = "free"

    # 2. Assign ARR with fallback
    arr = float(arr_value) if (arr_value is not None and arr_value > 0) else TIER_DEFAULT_ARR[tier]

    # 3. Customer ID placeholder
    cid = customer_id.strip() if customer_id else f"anon_{fallback_fingerprint[:8]}"

    # 4. Churn risk flag
    churn_flag = detect_churn_intent(clean_content)

    return cid, tier, arr, churn_flag


class NormalizedFeedbackItem:
    """Structured, deduplicated feedback ready for database storage and embedding."""

    def __init__(
        self,
        source_type: str,
        content: str,
        clean_content: str,
        fingerprint: str,
        customer_id: str,
        customer_tier: str,
        arr_value: float,
        churn_risk_flag: bool,
        external_id: Optional[str] = None,
        duplicate_count: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.source_type = source_type
        self.content = content
        self.clean_content = clean_content
        self.fingerprint = fingerprint
        self.customer_id = customer_id
        self.customer_tier = customer_tier
        self.arr_value = arr_value
        self.churn_risk_flag = churn_risk_flag
        self.external_id = external_id
        self.duplicate_count = duplicate_count
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "external_id": self.external_id,
            "content": self.content,
            "clean_content": self.clean_content,
            "fingerprint": self.fingerprint,
            "customer_id": self.customer_id,
            "customer_tier": self.customer_tier,
            "arr_value": self.arr_value,
            "churn_risk_flag": self.churn_risk_flag,
            "duplicate_count": self.duplicate_count,
            "metadata": self.metadata,
        }


def normalize_and_deduplicate(
    items: List[Dict[str, Any] | RawFeedbackItem],
    near_duplicate_threshold: float = 0.85,
) -> Tuple[List[NormalizedFeedbackItem], int]:
    """
    Main normalization engine function:
    1. Cleans and standardizes incoming text.
    2. Enforces customer metadata placeholders (tier defaults, churn detection, customer ID).
    3. Deduplicates via exact lexical fingerprinting and near-duplicate n-gram similarity.
    Returns: (normalized_items, duplicate_count)
    """
    seen_fingerprints: Dict[str, NormalizedFeedbackItem] = {}
    canonical_items: List[NormalizedFeedbackItem] = []
    total_duplicates_found = 0

    for item in items:
        # Convert Pydantic model to dict if needed
        data = item.model_dump() if isinstance(item, RawFeedbackItem) else item

        source_type = data.get("source_type", "unknown")
        raw_content = data.get("content", "")
        cleaned = clean_text(raw_content)

        if not cleaned:
            continue

        fingerprint = compute_lexical_fingerprint(cleaned)

        # 1. Check exact lexical duplicate
        if fingerprint in seen_fingerprints:
            existing = seen_fingerprints[fingerprint]
            existing.duplicate_count += 1
            # Inherit highest ARR and churn flag
            current_arr = float(data.get("arr_value", 0.0))
            if current_arr > existing.arr_value:
                existing.arr_value = current_arr
            if data.get("churn_risk_flag") or detect_churn_intent(cleaned):
                existing.churn_risk_flag = True
            total_duplicates_found += 1
            continue

        # 2. Check near-duplicate matching against existing canonical items
        is_near_duplicate = False
        for canonical in canonical_items:
            sim = compute_similarity(cleaned, canonical.clean_content)
            if sim >= near_duplicate_threshold:
                canonical.duplicate_count += 1
                current_arr = float(data.get("arr_value", 0.0))
                if current_arr > canonical.arr_value:
                    canonical.arr_value = current_arr
                if data.get("churn_risk_flag") or detect_churn_intent(cleaned):
                    canonical.churn_risk_flag = True
                is_near_duplicate = True
                total_duplicates_found += 1
                break

        if is_near_duplicate:
            continue

        # 3. Structure metadata placeholders
        cid, tier, arr, churn_flag = structure_customer_metadata(
            customer_id=data.get("customer_id"),
            customer_tier=data.get("customer_tier"),
            arr_value=data.get("arr_value"),
            clean_content=cleaned,
            fallback_fingerprint=fingerprint,
        )

        normalized_obj = NormalizedFeedbackItem(
            source_type=source_type,
            content=raw_content,
            clean_content=cleaned,
            fingerprint=fingerprint,
            customer_id=cid,
            customer_tier=tier,
            arr_value=arr,
            churn_risk_flag=churn_flag,
            external_id=data.get("external_id"),
            metadata=data.get("metadata", {}),
        )

        seen_fingerprints[fingerprint] = normalized_obj
        canonical_items.append(normalized_obj)

    return canonical_items, total_duplicates_found
