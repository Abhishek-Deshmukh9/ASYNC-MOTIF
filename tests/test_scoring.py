from datetime import datetime, timedelta, timezone

import pytest

from app.core.scoring import PROFILES, _percentiles, compute_signals, score_themes


def item(customer=None, arr=0.0, churn=False, source="email", speaker=None, tier="free", when=None, text="Exports keep failing"):
    return {
        "id": f"{customer}-{speaker}-{source}-{text}-{when}",
        "customer_id": customer,
        "arr_value": arr,
        "churn_risk_flag": churn,
        "source_type": source,
        "source_name": None,
        "speaker": speaker,
        "customer_tier": tier,
        "occurred_at": when,
        "content": text,
    }


def theme(items, cohesion=0.6, quotes=3):
    return {"items": items, "cohesion": cohesion, "verified_quotes": quotes}


def test_reach_counts_each_customer_once():
    s = compute_signals([item("acme"), item("acme"), item("acme"), item("bolt")])
    assert s["reach"]["raw"] == 2
    assert s["reach"]["evidence"][0] == {"name": "acme", "kind": "customer", "mentions": 3}


def test_reach_falls_back_to_speakers_then_sources():
    people = compute_signals([item(speaker="Maya"), item(speaker="maya"), item(speaker="Raj")])["reach"]
    assert people["raw"] == 2 and people["basis"] == "person"
    sources = compute_signals([item(source="email"), item(source="slack")])["reach"]
    assert sources["raw"] == 2 and sources["basis"] == "source"


def test_revenue_counts_each_account_once_at_its_largest_value():
    s = compute_signals([item("acme", 50000), item("acme", 40000), item("bolt", 10000), item("anon", 0)])["revenue"]
    assert s["raw"] == 60000
    assert [e["name"] for e in s["evidence"]] == ["acme", "bolt"]


def test_urgency_is_share_of_reporters_not_messages():
    s = compute_signals([item("a", churn=True), item("a", churn=True), item("b"), item("c"), item("d")])["urgency"]
    assert s["raw"] == pytest.approx(0.25)
    assert s["evidence"][0]["name"] == "a"


def test_percentiles_handle_ties_and_single_theme():
    assert _percentiles([5]) == [0.5]
    assert _percentiles([1, 2, 3]) == [0.0, 0.5, 1.0]
    assert _percentiles([2, 2, 9]) == [0.25, 0.25, 1.0]


def test_signals_without_data_are_dropped_and_weights_still_sum_to_one():
    themes = [theme([item("a"), item("b")]), theme([item("c")])]
    result = score_themes(themes, project_source_count=1)
    dropped = {d["key"] for d in result[0]["dropped"]}
    assert {"revenue", "breadth", "momentum", "strategic"} <= dropped
    assert {s["key"] for s in result[0]["signals"]} == {"reach", "urgency"}
    assert sum(s["weight"] for s in result[0]["signals"]) == pytest.approx(1.0, abs=1e-3)
    assert all("No customer ARR" in d["reason"] for d in result[0]["dropped"] if d["key"] == "revenue")


def test_momentum_uses_real_dates_and_reports_the_counts():
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    rising = [item(f"c{i}", when=now - timedelta(days=i % 10), text=f"r{i}") for i in range(8)] + [item("o1", when=now - timedelta(days=20), text="old")]
    fading = [item(f"f{i}", when=now - timedelta(days=15 + i), text=f"f{i}") for i in range(6)]
    result = score_themes([theme(rising), theme(fading)], project_source_count=2)
    momentum = [s for s in result[0]["signals"] if s["key"] == "momentum"][0]
    assert "8 mentions in the last 14 days vs 1 before" in momentum["display"]
    assert momentum["evidence"][0]["mentions"] == 8
    assert result[0]["priority_score"] > result[1]["priority_score"]


def test_no_event_dates_means_momentum_is_dropped_not_guessed():
    result = score_themes([theme([item("a")]), theme([item("b")])], project_source_count=2)
    assert "momentum" in {d["key"] for d in result[0]["dropped"]}


def test_biggest_problem_ranks_first_and_verdict_cites_the_numbers():
    big = theme([item(f"c{i}", 20000, churn=(i < 3), tier="enterprise") for i in range(6)])
    small = theme([item("x", 1000), item("y", 1000)])
    result = score_themes([small, big], project_source_count=2)
    assert result[1]["rank"] == 1 and result[0]["rank"] == 2
    assert result[1]["verdict"].startswith("Ranked #1 of 2:")
    assert "6 customers" in result[1]["verdict"]


def test_profile_changes_what_wins_and_says_so():
    few_big = theme([item("a", 100000), item("b", 100000)])
    many_small = theme([item(f"s{i}", 1000) for i in range(8)])
    saas = score_themes([few_big, many_small], profile="b2b_saas", project_source_count=2)
    dev = score_themes([few_big, many_small], profile="dev_tools", project_source_count=2)
    assert saas[0]["rank"] == 1 and saas[0]["profile"] == "b2b_saas"
    assert dev[1]["rank"] == 1 and dev[1]["profile_label"] == "Developer tools"


def test_thin_evidence_is_flagged_in_the_verdict():
    result = score_themes([theme([item("a")], quotes=1), theme([item("b"), item("c"), item("d")], quotes=3)], project_source_count=2)
    assert result[0]["confidence"]["level"] == "thin" and "Thin evidence" in result[0]["verdict"]
    assert result[1]["confidence"]["level"] == "supported"


def test_unknown_profile_falls_back_to_default():
    assert score_themes([theme([item("a")])], profile="nonsense")[0]["profile"] == "b2b_saas"


def test_profile_weights_are_complete_and_sum_to_one():
    for profile in PROFILES.values():
        assert sum(profile["weights"].values()) == pytest.approx(1.0)


def test_each_parameter_has_a_short_value_note_and_maximum_for_the_card():
    themes = [theme([item("a", 50000, churn=True, tier="enterprise"), item("b", 10000)]), theme([item("c", 1000)])]
    result = score_themes(themes, project_source_count=1)
    signals = {s["key"]: s for s in result[0]["signals"]}
    assert signals["reach"]["value"] == "2 customers" and "each customer counted once" in signals["reach"]["note"]
    assert signals["revenue"]["value"] == "$60,000" and signals["revenue"]["note"] == "yearly value of 2 customers"
    assert signals["urgency"]["value"] == "50%" and signals["urgency"]["note"] == "1 of 2 mention cancelling or switching"
    assert signals["strategic"]["value"] == "1 of 2"
    # points never exceed the parameter's maximum, and the maxima add up to 100
    assert all(s["points"] <= s["max_points"] + 1e-9 for s in result[0]["signals"])
    assert sum(s["max_points"] for s in result[0]["signals"]) == pytest.approx(100, abs=0.05)
    assert {d["key"]: d["short"] for d in result[0]["dropped"]} == {"breadth": "only one source", "momentum": "no event dates"}


def test_people_not_persons():
    s = compute_signals([item(speaker="Maya"), item(speaker="Raj")])["reach"]
    assert s["value"] == "2 people" and s["display"] == "2 people"


def test_a_theme_with_none_of_a_parameter_earns_nothing_for_it():
    themes = [theme([item("a", churn=True), item("b")]), theme([item("c"), item("d")]), theme([item("e")])]
    result = score_themes(themes, project_source_count=1)
    urgency = [next(s for s in r["signals"] if s["key"] == "urgency") for r in result]
    assert urgency[0]["points"] > 0
    assert urgency[1]["points"] == 0 and urgency[2]["points"] == 0  # 0% churn language -> +0, even though tied
