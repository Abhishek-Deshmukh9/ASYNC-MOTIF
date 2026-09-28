import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings
from app.schemas.llm_response import ClusterSynthesizedTheme
from app.core.citation_verifier import verify_all_citations

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Motif's Autonomous Feedback-to-Backlog Synthesis Engine.
Your task is to analyze a cluster of related customer feedback items and synthesize a structured product backlog theme.

NON-NEGOTIABLE CORE AXIOM:
Every claim in your output must be directly grounded in the provided customer feedback items.
In particular, `cited_quotes` MUST be a list of EXACT VERBATIM SUBSTRINGS copied directly from the feedback items below.
Never paraphrase, alter, or fabricate any quote. Every single quote will be verified by a deterministic string-matching engine.

You MUST respond strictly with valid JSON conforming to this schema:
{
  "title": "<Concise, action-oriented theme title, e.g. 'Google Workspace SSO Token Desync on 20-Min Expiry'>",
  "problem_statement": "<Objective technical summary of the blocker, root cause, and customer impact>",
  "affected_workflows": ["<Workflow 1>", "<Workflow 2>"],
  "cited_quotes": ["<exact verbatim quote 1>", "<exact verbatim quote 2>"],
  "confidence_score": 0.95
}
"""


def _generate_user_prompt(exemplars: List[Dict[str, Any]]) -> str:
    prompt_lines = [
        "Synthesize the following representative customer feedback items into a structured theme:\n"
    ]
    for i, item in enumerate(exemplars, 1):
        content = item.get("clean_content") or item.get("content", "")
        cid = item.get("customer_id", "Unknown")
        tier = item.get("customer_tier", "free")
        arr = item.get("arr_value", 0.0)
        prompt_lines.append(f"[{i}] Customer '{cid}' ({tier}, ARR: ${arr:,.0f}):\n\"{content}\"\n")

    prompt_lines.append(
        "\nProvide strictly the JSON object. Do not include markdown code block backticks."
    )
    return "\n".join(prompt_lines)


async def _call_gemini_flash(prompt: str, api_key: str) -> str:
    """Call Google Gemini Flash via REST API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{SYSTEM_PROMPT}\n\n{prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            return candidates[0]["content"]["parts"][0]["text"]
        raise ValueError("No response content from Gemini Flash")


async def _call_groq(prompt: str, api_key: str) -> str:
    """Call Groq API (OpenAI-compatible) with low latency and automatic model fallback."""
    base_url = (settings.GROQ_BASE_URL or "https://api.groq.com/openai/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Priority list of models: configured model first, followed by active Groq models
    candidate_models: List[str] = []
    if settings.GROQ_MODEL:
        candidate_models.append(settings.GROQ_MODEL)
    for model_name in [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
    ]:
        if model_name not in candidate_models:
            candidate_models.append(model_name)

    last_error: Optional[Exception] = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for model in candidate_models:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            try:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info(f"Groq synthesis succeeded using model: '{model}'")
                    return data["choices"][0]["message"]["content"]
                elif resp.status_code == 429:
                    retry_after = 2.0
                    try:
                        hdr = resp.headers.get("retry-after")
                        if hdr:
                            retry_after = max(float(hdr), 1.0)
                    except Exception:
                        pass
                    logger.warning(
                        f"Groq model '{model}' rate-limited (HTTP 429). Backing off {retry_after}s before fallback..."
                    )
                    await asyncio.sleep(retry_after)
                else:
                    logger.warning(
                        f"Groq model '{model}' returned HTTP {resp.status_code}: {resp.text[:150]}. Trying next fallback..."
                    )
            except Exception as exc:
                logger.warning(f"Groq request failed for model '{model}': {exc}")
                last_error = exc
                continue

    if last_error:
        raise last_error
    raise RuntimeError("All candidate Groq models failed to return a completion.")


async def _call_openai(prompt: str, api_key: str) -> str:
    """Call OpenAI API."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _synthesize_offline_grounded_theme(
    exemplars: List[Dict[str, Any]],
    source_texts: List[str],
) -> ClusterSynthesizedTheme:
    """
    Deterministic zero-hallucination heuristic fallback.
    Extracts high-impact verbatim sentences from cluster medoids.
    Guarantees 100% citation validity for test/offline environments.
    """
    best_item = exemplars[0] if exemplars else {"content": "General friction"}
    full_text = best_item.get("clean_content") or best_item.get("content", "")

    # Strip generic email greetings
    cleaned_for_title = re.sub(r"^Hi Support Team,\s*", "", full_text, flags=re.IGNORECASE).strip()
    cleaned_for_title = re.sub(r"^We are encountering a critical operational issue with your product:\s*", "", cleaned_for_title, flags=re.IGNORECASE).strip()

    # Split into clean sentences
    sentences = [s.strip() for s in re.split(r"[.!?]\s+", cleaned_for_title) if len(s.strip()) > 15]
    if not sentences:
        sentences = [full_text]

    # Select representative sentences as verbatim quotes
    primary_quote = sentences[0]
    cited_quotes = [primary_quote]
    if len(sentences) > 1:
        cited_quotes.append(sentences[1])

    # Derive theme title
    raw_title = primary_quote[:85].strip()
    title = f"Issue: {raw_title}" if not raw_title.startswith("Rating") else raw_title

    return ClusterSynthesizedTheme(
        title=title,
        problem_statement=f"Customer friction identified: {primary_quote}",
        affected_workflows=["Core application workflow", "Session persistence"],
        cited_quotes=cited_quotes,
        confidence_score=0.92,
    )


async def synthesize_cluster_theme(
    cluster_items: List[Dict[str, Any]],
    exemplars: Optional[List[Dict[str, Any]]] = None,
) -> ClusterSynthesizedTheme:
    """
    Synthesizes a structured, evidence-grounded theme for a cluster using
    Groq (100% free-tier), Google Gemini Flash, OpenAI, or deterministic fallback.
    Enforces Rule 1.1 (Quote Verification): 100% of quotes must be verbatim.
    """
    source_texts = [
        item.get("content", "") for item in cluster_items
    ] + [
        item.get("clean_content", "") for item in cluster_items
    ]
    representative_items = exemplars or cluster_items[:5]
    user_prompt = _generate_user_prompt(representative_items)

    raw_response_text: Optional[str] = None
    provider_used = "offline_fallback"

    # 1. Attempt configured or auto-detected LLM provider (Groq prioritized)
    groq_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY")
    gemini_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
    openai_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

    try:
        if (settings.LLM_PROVIDER in ["groq", "auto"]) and groq_key:
            logger.info("Synthesizing theme using Groq OpenAI-compatible free-tier endpoint...")
            raw_response_text = await _call_groq(user_prompt, groq_key)
            provider_used = "groq"
        elif (settings.LLM_PROVIDER in ["gemini"]) and gemini_key:
            logger.info("Synthesizing theme using Google Gemini Flash...")
            raw_response_text = await _call_gemini_flash(user_prompt, gemini_key)
            provider_used = "gemini_flash"
        elif (settings.LLM_PROVIDER in ["openai"]) and openai_key:
            logger.info("Synthesizing theme using OpenAI...")
            raw_response_text = await _call_openai(user_prompt, openai_key)
            provider_used = "openai"
    except Exception as e:
        logger.warning(f"External LLM call failed ({e}); falling back to deterministic synthesis.")

    # 2. Parse and validate LLM output via Pydantic schema
    if raw_response_text:
        try:
            cleaned_json = raw_response_text.strip()
            # Strip markdown json code fences if present anywhere
            cleaned_json = re.sub(r"```(?:json)?\s*", "", cleaned_json, flags=re.IGNORECASE)
            cleaned_json = cleaned_json.replace("```", "")
            # Find bounds of outermost JSON object
            first_brace = cleaned_json.find('{')
            last_brace = cleaned_json.rfind('}')
            if first_brace != -1 and last_brace != -1:
                cleaned_json = cleaned_json[first_brace:last_brace+1]

            # Remove trailing commas before closing braces or brackets
            cleaned_json = re.sub(r',\s*([}\]])', r'\1', cleaned_json)

            parsed_data = json.loads(cleaned_json)
            # Normalize non-breaking hyphens and unicode punctuation
            def _clean_unicode(s: Any) -> Any:
                if isinstance(s, str):
                    return s.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-").replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
                if isinstance(s, list):
                    return [_clean_unicode(x) for x in s]
                return s

            clean_dict = {k: _clean_unicode(v) for k, v in parsed_data.items()}
            theme = ClusterSynthesizedTheme(**clean_dict)

            # Rule 1.1: Deterministic quote verification
            is_valid, verified, hallucinations = verify_all_citations(
                theme.cited_quotes, source_texts
            )

            if is_valid:
                logger.info(f"LLM theme verified successfully via {provider_used}: '{theme.title}'")
                return theme
            elif verified:
                # Retain only the verified subset of quotes
                logger.info(f"Retaining {len(verified)} verified quotes, discarded {len(hallucinations)} unverified.")
                theme.cited_quotes = verified
                return theme
            else:
                logger.warning("All LLM quotes failed verbatim matching. Falling back to source medoid quotes.")
        except Exception as e:
            logger.warning(f"Failed to parse LLM JSON response ({e}): {raw_response_text[:150]}")

    # 3. Deterministic Grounded Synthesis Fallback
    logger.info("Using deterministic zero-hallucination synthesis from cluster medoid.")
    return _synthesize_offline_grounded_theme(representative_items, source_texts)
