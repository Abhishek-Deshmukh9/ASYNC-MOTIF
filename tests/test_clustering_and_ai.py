import pytest
import numpy as np
from app.core.clustering import cluster_feedback_embeddings, ClusterResult
from app.core.citation_verifier import verify_all_citations, verify_quote_against_pool
from app.core.ranker import calculate_revenue_at_risk
from app.core.llm_labeler import synthesize_cluster_theme


def test_hdbscan_clustering_identifies_clusters_and_noise():
    """
    Unit test for HDBSCAN clustering engine:
    Verifies that dense clusters are grouped and off-topic outliers are labeled -1 (Noise).
    """
    np.random.seed(42)
    dim = 384

    # Create Cluster A (center: [1, 0, 0, ...])
    center_a = np.zeros(dim)
    center_a[0] = 1.0
    cluster_a = [
        center_a + np.random.normal(0, 0.02, dim) for _ in range(6)
    ]

    # Create Cluster B (center: [0, 1, 0, ...])
    center_b = np.zeros(dim)
    center_b[1] = 1.0
    cluster_b = [
        center_b + np.random.normal(0, 0.02, dim) for _ in range(6)
    ]

    # Create Noise Outliers (far away random vectors)
    outlier_1 = np.random.normal(0, 1.0, dim)
    outlier_2 = np.random.normal(0, 1.0, dim)

    # Normalize all vectors to unit length
    all_raw = cluster_a + cluster_b + [outlier_1, outlier_2]
    all_normalized = [v / np.linalg.norm(v) for v in all_raw]

    items = []
    for i, vec in enumerate(all_normalized):
        items.append({
            "id": f"item_{i}",
            "content": f"Feedback content for item {i}",
            "clean_content": f"Feedback content for item {i}",
            "customer_id": f"cust_{i}",
            "arr_value": 1000.0,
            "churn_risk_flag": False,
            "embedding": vec.tolist(),
        })

    result: ClusterResult = cluster_feedback_embeddings(
        items,
        min_cluster_size=4,
        min_samples=2,
    )

    # Must discover dense clusters
    assert result.total_dense_clusters >= 2
    # Outliers or sparse items must be categorized into noise_items
    assert isinstance(result.noise_items, list)
    for n in result.noise_items:
        assert n["cluster_label"] == -1


def test_cluster_cohesion_and_medoids():
    """
    Verifies that cohesion scores and medoid exemplars are properly computed.
    """
    dim = 384
    center = np.zeros(dim)
    center[0] = 1.0
    # Very tight cluster
    vecs = [center + np.random.normal(0, 0.005, dim) for _ in range(5)]
    normalized = [v / np.linalg.norm(v) for v in vecs]

    items = [
        {
            "id": f"c_{i}",
            "content": f"SSO token expiration bug message {i}",
            "customer_id": f"user_{i}",
            "arr_value": 50000.0,
            "embedding": v.tolist(),
        }
        for i, v in enumerate(normalized)
    ]

    result = cluster_feedback_embeddings(items, min_cluster_size=3, min_samples=2)
    assert result.total_dense_clusters >= 1
    for cid, score in result.cohesion_scores.items():
        # High density cluster should have cohesion close to 1.0
        assert score > 0.8
    for cid, exemplars in result.exemplars.items():
        assert len(exemplars) > 0


def test_citation_verifier_catches_hallucinations():
    """
    Enforces Rule 1.1: Quote verification must pass exact substrings
    and reject altered/hallucinated text.
    """
    source_pool = [
        "Google Workspace SSO tokens expire after 20 minutes and force users to re-login.",
        "Exporting CSV reports with more than 10,000 rows silently truncates output.",
    ]

    # 1. Exact verbatim quotes
    exact_quotes = [
        "Google Workspace SSO tokens expire after 20 minutes",
        "silently truncates output",
    ]
    is_valid, verified, hallucinations = verify_all_citations(exact_quotes, source_pool)
    assert is_valid is True
    assert len(verified) == 2
    assert len(hallucinations) == 0

    # 2. Fabricated or paraphrased quote
    altered_quotes = [
        "Google Workspace SSO tokens expire after 20 minutes",  # Valid
        "Users are kicked out and lose their work constantly",  # Hallucinated paraphrase
    ]
    is_valid, verified, hallucinations = verify_all_citations(altered_quotes, source_pool)
    assert is_valid is False
    assert len(verified) == 1
    assert len(hallucinations) == 1
    assert "Users are kicked out" in hallucinations[0]


def test_revenue_at_risk_ranking():
    """
    Enforces Rule 1.4: High ARR enterprise churn threat outranks low-value complaints.
    """
    enterprise_cluster = [
        {"customer_id": "acme", "arr_value": 120000.0, "churn_risk_flag": True},
        {"customer_id": "globex", "arr_value": 85000.0, "churn_risk_flag": True},
    ]

    free_tier_cluster = [
        {"customer_id": f"free_{i}", "arr_value": 0.0, "churn_risk_flag": False}
        for i in range(50)
    ]

    score_ent = calculate_revenue_at_risk(enterprise_cluster, cohesion_score=1.0)
    score_free = calculate_revenue_at_risk(free_tier_cluster, cohesion_score=1.0)

    assert score_ent["revenue_at_risk"] == 205000.0
    assert score_free["revenue_at_risk"] == 0.0
    assert score_ent["priority_score"] > score_free["priority_score"]


@pytest.mark.anyio
async def test_llm_theme_synthesis_grounding():
    """
    Tests theme synthesis ensuring generated quotes are 100% grounded in source items.
    """
    items = [
        {
            "content": "Google Workspace SSO tokens expire after 20 minutes and force users to re-login in the middle of active editing sessions.",
            "clean_content": "Google Workspace SSO tokens expire after 20 minutes and force users to re-login in the middle of active editing sessions.",
            "customer_id": "cust_acme_corp",
            "customer_tier": "enterprise",
            "arr_value": 120000.0,
            "churn_risk_flag": True,
        },
        {
            "content": "Our IT department has flagged this as an SLA violation. If SSO session persistence isn't resolved by next month we are cancelling our 200-seat contract.",
            "clean_content": "Our IT department has flagged this as an SLA violation. If SSO session persistence isn't resolved by next month we are cancelling our 200-seat contract.",
            "customer_id": "cust_acme_corp",
            "customer_tier": "enterprise",
            "arr_value": 120000.0,
            "churn_risk_flag": True,
        }
    ]

    theme = await synthesize_cluster_theme(items)
    assert theme.title is not None
    assert len(theme.cited_quotes) >= 1

    # Verify that all cited quotes are 100% verbatim
    source_texts = [x["content"] for x in items] + [x["clean_content"] for x in items]
    is_valid, verified, hallucinations = verify_all_citations(theme.cited_quotes, source_texts)
    assert is_valid is True
    assert len(hallucinations) == 0
