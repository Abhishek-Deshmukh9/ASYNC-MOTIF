"""
Motif Full-Stack Diagnostic Script
Checks: DB connection, feedback items, embeddings, themes, Groq API, backend endpoints, frontend contract
"""
import asyncio
import os
import sys
import json
import time

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dotenv
dotenv.load_dotenv()

import httpx

BACKEND = "http://localhost:8000"
RESULTS = {"pass": [], "fail": [], "warn": []}

def P(msg): RESULTS["pass"].append(msg); print(f"  [PASS] {msg}")
def F(msg): RESULTS["fail"].append(msg); print(f"  [FAIL] {msg}")
def W(msg): RESULTS["warn"].append(msg); print(f"  [WARN] {msg}")


async def check_backend_alive():
    print("\n[1] Backend Server Reachability")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{BACKEND}/")
        if r.status_code == 200:
            P(f"Backend alive at {BACKEND} (HTTP {r.status_code})")
        else:
            F(f"Backend returned HTTP {r.status_code}")
    except Exception as e:
        F(f"Backend unreachable: {e}")


async def check_health_endpoint():
    print("\n[2] Health Endpoint (/api/v1/health)")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{BACKEND}/api/v1/health")
        data = r.json()
        if r.status_code == 200:
            db_status = data.get("database", {}).get("database", "unknown")
            pgv = data.get("database", {}).get("pgvector_extension", "unknown")
            P(f"Health OK -- DB: {db_status}, pgvector: {pgv}, latency: {data.get('database',{}).get('latency_ms')}ms")
        else:
            F(f"Health endpoint returned HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        F(f"Health endpoint error: {e}")


async def check_db_feedback_count():
    print("\n[3] Database -- Feedback Items & Embeddings")
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.feedback import FeedbackItem
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as session:
            total = await session.scalar(select(func.count(FeedbackItem.id)))
            embedded = await session.scalar(
                select(func.count(FeedbackItem.id)).where(FeedbackItem.embedding.isnot(None))
            )
            unembedded = total - embedded
            P(f"Total feedback items: {total}")
            if embedded > 0:
                P(f"Embedded items: {embedded}")
            else:
                F(f"No embedded items found (embedded={embedded}). Pipeline cannot cluster.")
            if unembedded > 0:
                W(f"{unembedded} items still un-embedded -- pipeline will embed these first")
    except Exception as e:
        F(f"DB query failed: {e}")


async def check_db_themes():
    print("\n[4] Database -- Themes")
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.theme import Theme
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as session:
            total = await session.scalar(select(func.count(Theme.id)))
            pending = await session.scalar(
                select(func.count(Theme.id)).where(Theme.status == "pending_review")
            )
            approved = await session.scalar(
                select(func.count(Theme.id)).where(Theme.status == "approved")
            )
            if total > 0:
                P(f"Themes in DB: {total} (pending={pending}, approved={approved})")
            else:
                F(f"No themes in database. Pipeline has not generated themes yet.")
    except Exception as e:
        F(f"DB theme query failed: {e}")


async def check_themes_endpoint():
    print("\n[5] Themes REST Endpoint (GET /api/v1/themes)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BACKEND}/api/v1/themes")
        if r.status_code == 200:
            themes = r.json()
            if len(themes) > 0:
                top = themes[0]
                P(f"Themes endpoint returned {len(themes)} themes.")
                P(f"Top theme: '{top['title']}' (${top['revenue_at_risk']:,.0f})")
                if top.get("cited_quotes") and len(top["cited_quotes"]) > 0:
                    P(f"Top theme has {len(top['cited_quotes'])} cited quotes")
                else:
                    W(f"Top theme has NO cited_quotes -- quotes may not be linking properly")
            else:
                F(f"Themes endpoint returned EMPTY array (0 themes). UI will show nothing.")
        else:
            F(f"Themes endpoint HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        F(f"Themes endpoint error: {e}")


async def check_metrics_endpoint():
    print("\n[6] Metrics REST Endpoint (GET /api/v1/metrics/eval)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BACKEND}/api/v1/metrics/eval")
        if r.status_code == 200:
            data = r.json()
            P(f"Metrics OK -- P@3: {data['precision_at_3']}%, Acceptance: {data['acceptance_rate']}%, ARR: ${data['total_revenue_at_risk']:,.0f}")
        else:
            F(f"Metrics endpoint HTTP {r.status_code}")
    except Exception as e:
        F(f"Metrics endpoint error: {e}")


async def check_pipeline_endpoint():
    print("\n[7] Pipeline Status Endpoint (GET /api/v1/pipeline/status)")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{BACKEND}/api/v1/pipeline/status")
        if r.status_code == 200:
            data = r.json()
            P(f"Pipeline status: {data['status']}")
            if data.get("error"):
                W(f"Last pipeline error recorded: {data['error'][:150]}")
        else:
            F(f"Pipeline status endpoint HTTP {r.status_code}")
    except Exception as e:
        F(f"Pipeline status error: {e}")


async def check_groq_api_key():
    print("\n[8] Groq API Key & Model Availability")
    from app.config import settings
    key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY")
    if not key:
        F("GROQ_API_KEY is not set in .env or config!")
        return
    P(f"GROQ_API_KEY present (length={len(key)})")
    P(f"LLM_PROVIDER={settings.LLM_PROVIDER}, GROQ_MODEL={settings.GROQ_MODEL}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"}
            )
        if r.status_code == 200:
            models = [m["id"] for m in r.json().get("data", [])]
            P(f"Groq models accessible: {len(models)} models")
            if settings.GROQ_MODEL in models:
                P(f"Configured model '{settings.GROQ_MODEL}' is available")
            else:
                W(f"Configured model '{settings.GROQ_MODEL}' NOT in available models -- fallback will activate")
                available = [m for m in models if "gpt-oss" in m or "llama" in m or "qwen" in m]
                P(f"Fallback-capable models on key: {available}")
        else:
            F(f"Groq models endpoint HTTP {r.status_code}")
    except Exception as e:
        F(f"Groq API check failed: {e}")


async def check_groq_synthesis():
    print("\n[9] Groq End-to-End Synthesis Test")
    from app.core.llm_labeler import synthesize_cluster_theme
    items = [
        {
            "customer_id": "test_cust_1", "customer_tier": "enterprise", "arr_value": 50000.0,
            "content": "Our SSO tokens expire every 20 minutes forcing re-login.",
            "clean_content": "Our SSO tokens expire every 20 minutes forcing re-login.",
        },
        {
            "customer_id": "test_cust_2", "customer_tier": "enterprise", "arr_value": 30000.0,
            "content": "SSO token refresh fails silently during active editing sessions.",
            "clean_content": "SSO token refresh fails silently during active editing sessions.",
        },
    ]
    try:
        theme = await synthesize_cluster_theme(items)
        P(f"Synthesis succeeded: title='{theme.title}', quotes={len(theme.cited_quotes)}, confidence={theme.confidence_score}")
    except Exception as e:
        F(f"Synthesis crashed: {e}")


async def check_frontend_cors():
    print("\n[10] CORS Preflight Check (frontend -> backend)")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.options(
                f"{BACKEND}/api/v1/themes",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                }
            )
        cors_header = r.headers.get("access-control-allow-origin", "")
        if "localhost:3000" in cors_header or cors_header == "*":
            P(f"CORS OK for localhost:3000 (header: {cors_header})")
        else:
            F(f"CORS blocked! access-control-allow-origin='{cors_header}'")
    except Exception as e:
        F(f"CORS check failed: {e}")


async def check_pipeline_run_trigger():
    print("\n[11] Pipeline POST /api/v1/pipeline/run (dry-run check)")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.options(f"{BACKEND}/api/v1/pipeline/run")
        if r.status_code in (200, 204, 405):
            P(f"Pipeline run endpoint reachable (OPTIONS -> {r.status_code})")
        else:
            W(f"Pipeline run endpoint returned {r.status_code}")
    except Exception as e:
        F(f"Pipeline run endpoint unreachable: {e}")


async def main():
    print("=" * 70)
    print("  MOTIF FULL-STACK DIAGNOSTIC")
    print("=" * 70)

    await check_backend_alive()
    await check_health_endpoint()
    await check_db_feedback_count()
    await check_db_themes()
    await check_themes_endpoint()
    await check_metrics_endpoint()
    await check_pipeline_endpoint()
    await check_groq_api_key()
    await check_groq_synthesis()
    await check_frontend_cors()
    await check_pipeline_run_trigger()

    print("\n" + "=" * 70)
    print(f"  RESULTS: {len(RESULTS['pass'])} passed, {len(RESULTS['fail'])} failed, {len(RESULTS['warn'])} warnings")
    print("=" * 70)
    if RESULTS["fail"]:
        print("\n  FAILURES:")
        for f in RESULTS["fail"]:
            print(f"    [FAIL] {f}")
    if RESULTS["warn"]:
        print("\n  WARNINGS:")
        for w in RESULTS["warn"]:
            print(f"    [WARN] {w}")
    print()

if __name__ == "__main__":
    asyncio.run(main())
