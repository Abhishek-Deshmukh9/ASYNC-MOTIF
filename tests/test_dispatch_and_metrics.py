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
async def test_github_dispatch_requires_real_credentials(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)
    with pytest.raises(RuntimeError, match="no GitHub issue was created"):
        await dispatch_github_issue(
            title="[MOTIF] Test Issue",
            body="## PRD Test Body",
            labels=["motif-approved", "test"],
            owner="test-org",
            repo="test-repo",
        )


def test_metrics_evaluation_endpoint():
    response = client.get("/api/v1/metrics/eval")
    assert response.status_code == 200
    data = response.json()

    assert "precision_at_3" in data
    assert data["precision_at_3"] >= 90.0
    assert "acceptance_rate" in data
    assert data["acceptance_rate"] >= 70.0
    assert data["citation_validity"] == 100.0
    assert "total_feedback_items" in data
    assert "total_themes_discovered" in data
