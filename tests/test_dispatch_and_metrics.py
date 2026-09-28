import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.prd_generator import generate_mini_prd
from app.core.github_client import dispatch_github_issue

client = TestClient(app)


def test_mini_prd_generation():
    title = "Google Workspace SSO Token Desync on 20-Min Expiry"
    summary = "Users are kicked out every 20 minutes due to silent token refresh failure."
    quotes = [
        {
            "quote_text": "Google Workspace SSO tokens expire after 20 minutes and force users to re-login in the middle of active editing sessions.",
            "customer_id": "cust_acme_corp",
            "arr_value": 120000.0,
            "customer_tier": "enterprise",
        }
    ]

    prd = generate_mini_prd(
        theme_title=title,
        problem_summary=summary,
        revenue_at_risk=120000.0,
        affected_accounts_count=1,
        cited_quotes=quotes,
        cluster_id=4,
    )

    assert "# [PRD]" in prd
    assert "$120,000.00" in prd
    assert "CRITICAL (P0 - Enterprise Churn Risk)" in prd
    assert "Google Workspace SSO tokens expire after 20 minutes" in prd
    assert "Scenario:" in prd
    assert "Given" in prd
    assert "When" in prd
    assert "Then" in prd


@pytest.mark.anyio
async def test_github_dispatch_without_token_creates_no_fake_link(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)
    receipt = await dispatch_github_issue(
        title="[MOTIF] Test Issue",
        body="## PRD Test Body",
        labels=["motif-approved", "test"],
        owner="test-org",
        repo="test-repo",
    )

    assert receipt["is_live"] is False
    assert receipt["issue_url"] is None
    assert receipt["issue_number"] is None
    assert "GITHUB_TOKEN" in receipt["message"]


def test_metrics_evaluation_endpoint():
    """Needs a running database (docker compose up -d postgres). Checks shape, not fixed values."""
    response = client.get("/api/v1/metrics/eval")
    assert response.status_code == 200
    data = response.json()

    for key in (
        "precision_at_3",
        "acceptance_rate",
        "citation_validity",
        "ground_truth_top_3",
        "total_feedback_items",
        "total_themes_discovered",
        "total_revenue_at_risk",
    ):
        assert key in data
    # Metrics are measured, so they are either null (nothing to measure yet) or a percentage
    for key in ("precision_at_3", "acceptance_rate", "citation_validity"):
        assert data[key] is None or 0.0 <= data[key] <= 100.0
