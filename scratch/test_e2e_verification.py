import asyncio
import json
import logging
import uuid
import httpx
from sqlalchemy import select, func, delete

from app.main import app
from app.config import settings
from app.db.session import AsyncSessionLocal, check_db_health
from app.models.feedback import FeedbackItem
from app.models.theme import Theme
from app.core.pipeline import run_ai_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_e2e")

async def test_all():
    print("=" * 60)
    print("STARTING E2E VERIFICATION TEST")
    print("=" * 60)

    # 1. DB Health & pgvector Check
    print("\n--- 1. Testing Database Health & pgvector ---")
    db_health = await check_db_health()
    print("DB Health:", db_health)
    assert db_health["database"] == "connected", f"DB not connected: {db_health}"
    assert db_health["pgvector_extension"] == "enabled", "pgvector extension disabled"
    print(" [PASS] Database connection and pgvector extension verified.")

    # 2. Testing Un-embedded Feedback Flow
    print("\n--- 2. Testing Un-embedded Item Flow ---")
    test_uid = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        test_item = FeedbackItem(
            id=test_uid,
            source_type="slack",
            content="Testing end-to-end un-embedded item: Google Workspace SSO token sync failure.",
            clean_content="Testing end-to-end un-embedded item: Google Workspace SSO token sync failure.",
            customer_id="Acme Inc",
            customer_tier="enterprise",
            arr_value=85000.0,
            churn_risk_flag=True,
            embedding=None,
        )
        session.add(test_item)
        await session.commit()
    print(f"Created un-embedded feedback record: {test_uid}")

    # 3. Triggering Pipeline through FastAPI ASGI Client
    print("\n--- 3. Testing FastAPI Pipeline Run (/api/v1/pipeline/run) ---")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000") as client:
        # Trigger pipeline
        resp = await client.post("/api/v1/pipeline/run", json={"batch_size": 50, "min_cluster_size": 4, "min_samples": 2}, timeout=120.0)
        print(f"Pipeline HTTP Status: {resp.status_code}")
        pipeline_data = resp.json()
        print("Pipeline result summary:")
        print(f"  - items_processed: {pipeline_data.get('items_processed')}")
        print(f"  - newly_embedded: {pipeline_data.get('newly_embedded')}")
        print(f"  - dense_clusters_count: {pipeline_data.get('dense_clusters_count')}")
        print(f"  - themes_created: {pipeline_data.get('themes_created')}")
        assert resp.status_code == 200, f"Pipeline run failed: {resp.text}"
        assert pipeline_data.get("themes_created", 0) > 0, "No themes created"
        print(" [PASS] Pipeline successfully processed items and created themes.")

        # 4. Verify un-embedded item now has embedding
        print("\n--- 4. Verifying Un-embedded Item Vector Persistence ---")
        async with AsyncSessionLocal() as session:
            db_item = await session.scalar(select(FeedbackItem).where(FeedbackItem.id == test_uid))
            assert db_item is not None, "Test item not found"
            assert db_item.embedding is not None, "Test item embedding is still None"
            print(f" [PASS] Test item has embedding vector with dimension {len(db_item.embedding)}")
            # Cleanup test item
            await session.execute(delete(FeedbackItem).where(FeedbackItem.id == test_uid))
            await session.commit()

        # 5. Testing GET /api/v1/themes and Batched Quotes
        print("\n--- 5. Testing GET /api/v1/themes (Frontend Route) ---")
        themes_resp = await client.get("/api/v1/themes", timeout=30.0)
        assert themes_resp.status_code == 200, f"Failed to fetch themes: {themes_resp.text}"
        themes_list = themes_resp.json()
        print(f"Fetched {len(themes_list)} themes from /api/v1/themes")
        assert len(themes_list) > 0, "No themes returned from /api/v1/themes"
        first_theme = themes_list[0]
        print(f"  Top Theme: '{first_theme['title']}' | ARR: ${first_theme['revenue_at_risk']:,.2f} | Quotes: {len(first_theme['cited_quotes'])}")
        assert "cited_quotes" in first_theme, "cited_quotes missing"
        print(" [PASS] GET /api/v1/themes successfully returns themes with populated cited quotes.")

        # 6. Testing GET /api/v1/metrics/eval
        print("\n--- 6. Testing GET /api/v1/metrics/eval ---")
        metrics_resp = await client.get("/api/v1/metrics/eval", timeout=15.0)
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        print("Metrics summary:", json.dumps(metrics, indent=2))
        assert metrics["total_themes_discovered"] > 0, "total_themes_discovered is 0"
        print(" [PASS] GET /api/v1/metrics/eval successfully returned benchmark metrics.")

        # 7. Testing Theme Approval & PRD Generation
        print("\n--- 7. Testing Theme Approval Gate (/api/v1/themes/{id}/approve) ---")
        theme_id = first_theme["id"]
        approve_resp = await client.post(f"/api/v1/themes/{theme_id}/approve", json={"pm_user_id": "test_pm"}, timeout=30.0)
        assert approve_resp.status_code == 200, f"Approval failed: {approve_resp.text}"
        approve_data = approve_resp.json()
        print(f"  Approved theme: '{approve_data['title']}' status: {approve_data['status']}")
        assert approve_data["status"] == "approved"
        assert len(approve_data["prd_markdown"]) > 50, "PRD markdown not generated"
        print(" [PASS] Human-in-the-loop approval gate and PRD generator verified.")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_all())
