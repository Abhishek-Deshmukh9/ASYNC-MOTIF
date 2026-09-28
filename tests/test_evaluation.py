import json
from pathlib import Path

from app.core.evaluation import (
    acceptance_rate,
    citation_validity,
    dominant_label,
    ground_truth_top_k,
    precision_at_k,
)
from app.core.ranker import calculate_revenue_at_risk

CORPUS = Path(__file__).resolve().parent.parent / "data" / "seed" / "corpus_300.json"


def _load_corpus():
    items = json.loads(CORPUS.read_text(encoding="utf-8"))
    return [
        {
            "customer_id": x["customer_id"],
            "arr_value": x["arr_value"],
            "churn_risk_flag": x["churn_risk_flag"],
            "ground_truth_theme": x["metadata"].get("ground_truth_theme"),
        }
        for x in items
    ]


def test_every_seed_item_has_a_ground_truth_label():
    assert all(item["ground_truth_theme"] for item in _load_corpus())


def test_ground_truth_top_3_on_seed_corpus():
    top_3 = ground_truth_top_k(_load_corpus(), k=3)
    assert top_3 == ["sso_desync", "billing_currency_bug", "export_truncation"]


def test_revenue_counts_each_account_once():
    # One $120k account complaining 20 times is $120k at risk, not $2.4M
    items = [{"customer_id": "acme", "arr_value": 120000.0, "churn_risk_flag": False}] * 20
    result = calculate_revenue_at_risk(items)
    assert result["revenue_at_risk"] == 120000.0
    assert result["affected_accounts_count"] == 1


def test_churn_flag_on_any_message_weights_the_account():
    items = [
        {"customer_id": "acme", "arr_value": 100.0, "churn_risk_flag": False},
        {"customer_id": "acme", "arr_value": 100.0, "churn_risk_flag": True},
    ]
    assert calculate_revenue_at_risk(items)["priority_score"] == 250.0


def test_dominant_label_and_purity():
    label, purity = dominant_label(["sso", "sso", "sso", "export", None])
    assert label == "sso"
    assert purity == 0.75
    assert dominant_label([None, None]) == (None, 0.0)


def test_precision_at_3_perfect_and_partial():
    gt = ["sso", "billing", "export"]
    assert precision_at_k(["export", "sso", "billing"], gt) == 100.0
    assert precision_at_k(["sso", "dark_mode", "billing"], gt) == 66.7


def test_precision_at_3_counts_duplicate_themes_once():
    # The same real problem split into two themes should not score twice
    assert precision_at_k(["sso", "sso", "billing"], ["sso", "billing", "export"]) == 66.7


def test_precision_is_none_without_data():
    assert precision_at_k([], ["sso"]) is None
    assert precision_at_k(["sso"], []) is None


def test_citation_validity_rechecks_quotes():
    rows = [
        ("tokens expire after 20 minutes", "SSO tokens expire after 20 minutes and force re-login"),
        ("users are kicked out hourly", "SSO tokens expire after 20 minutes and force re-login"),
    ]
    assert citation_validity(rows) == (50.0, 1, 2)
    assert citation_validity([]) == (None, 0, 0)


def test_acceptance_rate_is_none_before_any_decision():
    assert acceptance_rate(0, 0) is None
    assert acceptance_rate(3, 4) == 75.0
