import logging
from typing import List, Tuple, Dict, Any

logger = logging.getLogger(__name__)


def verify_quote_against_pool(quote: str, source_pool: List[str]) -> bool:
    """
    Deterministic substring verification rule (Rule 1.1):
    Checks whether the generated quote exists verbatim (ignoring leading/trailing whitespace)
    inside at least one of the source feedback texts.
    """
    cleaned_quote = quote.strip()
    if not cleaned_quote:
        return False

    unquoted = cleaned_quote.strip("\"'")
    return any(cleaned_quote in item or (unquoted and unquoted in item) for item in source_pool)



def verify_all_citations(
    cited_quotes: List[str],
    source_pool: List[str],
) -> Tuple[bool, List[str], List[str]]:
    """
    Validates a list of LLM-generated citations.
    Returns:
        (is_fully_valid, verified_quotes, unverified_hallucinations)
    """
    verified: List[str] = []
    hallucinated: List[str] = []

    for quote in cited_quotes:
        if verify_quote_against_pool(quote, source_pool):
            verified.append(quote)
        else:
            hallucinated.append(quote)

    is_valid = len(hallucinated) == 0 and len(verified) > 0
    if not is_valid:
        logger.warning(
            f"Citation verification failed: {len(hallucinated)} hallucinated or paraphrased quotes found: {hallucinated}"
        )

    return is_valid, verified, hallucinated
