"""
Transparent theme scoring.

Every signal is computed from stored data, comes with the evidence rows behind it, and carries a plain
statement of why it exists. Nothing here calls a model, so nothing can be hallucinated.

How a theme's priority is built:
  1. Each signal gets a raw value per theme (e.g. 12 distinct customers).
  2. Raw values are turned into a 0..1 percentile among the themes of the same project, so no signal wins
     just because its units are bigger. A raw value of zero (or a falling trend) scores 0.
  3. A signal that cannot be computed honestly for this project (no ARR supplied, no event dates...) is
     dropped, and its weight is shared among the rest. The result says which signals were dropped and why.
  4. priority = 100 * sum(weight * percentile) over the signals that remain.

The weights are product choices (see PROFILES), not scientific constants; they are shown with every score.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

MOMENTUM_WINDOW_DAYS = 14
MIN_DATED_ITEMS = 4
EVIDENCE_ROWS = 8

SIGNAL_INFO: Dict[str, Dict[str, str]] = {
    "reach": {
        "label": "Reach",
        "why": "A problem several different people hit is a pattern; one loud voice is an anecdote. Each person or account counts once, so repeating a complaint cannot inflate the score.",
        "how": "Distinct customers (or named speakers, or sources when neither is known) among the feedback in this theme.",
    },
    "revenue": {
        "label": "Revenue at risk",
        "why": "Money is the clearest way to compare problems that look equally common. It is the total yearly value of the accounts affected, counted once per account.",
        "how": "Sum of each affected customer's ARR, as supplied in the data. Needs an ARR column or a customer list; dropped when none exists.",
    },
    "urgency": {
        "label": "Churn urgency",
        "why": "People who say they will cancel or switch are telling you the cost of waiting. Frustration that stops short of leaving is real but cheaper to defer.",
        "how": "Share of reporters whose messages contain churn language (cancel, switch, leave, 'considering alternatives').",
    },
    "breadth": {
        "label": "Source spread",
        "why": "When calls, tickets and chat all raise the same problem, it is not an artefact of one channel or one notetaker. Independent confirmation makes a theme harder to dismiss.",
        "how": "Number of distinct sources (documents, channels, feedback channels) that mention the theme. Dropped when the project has only one source.",
    },
    "momentum": {
        "label": "Momentum",
        "why": "A problem getting worse needs attention sooner than one that is fading, even if the totals are the same today.",
        "how": f"Mentions in the last {MOMENTUM_WINDOW_DAYS} days against the {MOMENTUM_WINDOW_DAYS} days before, using each item's real event date. Dropped when items carry no event dates.",
    },
    "strategic": {
        "label": "Strategic accounts",
        "why": "A problem that reaches the accounts the business depends on matters more than the same problem among trial users.",
        "how": "Share of reporting customers on the enterprise tier. Dropped when no customer tiers are known.",
    },
}

PROFILES: Dict[str, Dict[str, Any]] = {
    "b2b_saas": {
        "label": "B2B SaaS",
        "weights": {"reach": 0.25, "revenue": 0.30, "urgency": 0.20, "breadth": 0.10, "momentum": 0.10, "strategic": 0.05},
    },
    "dev_tools": {
        "label": "Developer tools",
        "weights": {"reach": 0.35, "revenue": 0.05, "urgency": 0.15, "breadth": 0.15, "momentum": 0.25, "strategic": 0.05},
    },
}
DEFAULT_PROFILE = "b2b_saas"


# ---------------------------------------------------------------- helpers

def _reporter_key(item: Dict[str, Any]) -> Tuple[str, str]:
    """Who raised this piece of feedback: a customer, a named speaker, or failing both, the source it came from."""
    if item.get("customer_id"):
        return ("customer", str(item["customer_id"]).strip())
    speaker = (item.get("speaker") or "").strip()
    if speaker:
        return ("person", speaker.lower())
    source = item.get("source_name") or item.get("source_type")
    if source:
        return ("source", str(source))
    return ("item", str(item.get("id")))


def _source_key(item: Dict[str, Any]) -> Optional[str]:
    return item.get("source_name") or item.get("source_type")


def _snippet(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _percentiles(values: Sequence[float]) -> List[float]:
    """Rank each value among the others on a 0..1 scale (ties share their average rank)."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = average / (n - 1)
        i = j + 1
    return ranks


# ---------------------------------------------------------------- raw signals

def compute_signals(items: List[Dict[str, Any]], anchor: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """Raw value, display text and evidence for each signal of one theme."""
    by_reporter: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_reporter[_reporter_key(item)].append(item)

    # reach
    kinds = Counter(kind for kind, _ in by_reporter)
    basis = {"customer": "customer", "person": "person", "source": "source", "item": "message"}[kinds.most_common(1)[0][0]] if kinds else "customer"
    ranked_reporters = sorted(by_reporter.items(), key=lambda kv: -len(kv[1]))
    reach = {
        "raw": float(len(by_reporter)),
        "display": _plural(len(by_reporter), "person" if basis == "person" else basis).replace("persons", "people"),
        "basis": basis,
        "value": _plural(len(by_reporter), "person" if basis == "person" else basis).replace("persons", "people"),
        "note": f"{len(items)} mentions, each {basis if basis != 'person' else 'person'} counted once",
        "evidence": [{"name": key[1], "kind": key[0], "mentions": len(rows)} for key, rows in ranked_reporters[:EVIDENCE_ROWS]],
    }

    # revenue: one ARR per customer (their largest), only for named customers
    arr_by_customer: Dict[str, Tuple[float, str]] = {}
    for item in items:
        cid = item.get("customer_id")
        arr = float(item.get("arr_value") or 0.0)
        if cid and arr > 0 and arr >= arr_by_customer.get(str(cid), (0.0, ""))[0]:
            arr_by_customer[str(cid)] = (arr, item.get("customer_tier") or "")
    revenue_total = sum(a for a, _ in arr_by_customer.values())
    revenue = {
        "raw": revenue_total,
        "display": f"${revenue_total:,.0f} ARR",
        "value": f"${revenue_total:,.0f}",
        "note": f"yearly value of {_plural(len(arr_by_customer), 'customer')}",
        "evidence": [{"name": cid, "arr": arr, "tier": tier} for cid, (arr, tier) in sorted(arr_by_customer.items(), key=lambda kv: -kv[1][0])[:EVIDENCE_ROWS]],
    }

    # urgency
    flagged = [(key, rows) for key, rows in by_reporter.items() if any(r.get("churn_risk_flag") for r in rows)]
    share = len(flagged) / len(by_reporter) if by_reporter else 0.0
    quotes = []
    for key, rows in flagged[:3]:
        row = next(r for r in rows if r.get("churn_risk_flag"))
        quotes.append({"name": key[1], "text": _snippet(row.get("content") or "")})
    urgency = {
        "raw": share,
        "display": f"{round(share * 100)}% show churn language ({len(flagged)} of {len(by_reporter)})",
        "value": f"{round(share * 100)}%",
        "note": f"{len(flagged)} of {len(by_reporter)} mention cancelling or switching",
        "evidence": quotes,
    }

    # breadth
    sources = Counter(s for s in (_source_key(i) for i in items) if s)
    breadth = {
        "raw": float(len(sources)),
        "display": _plural(len(sources), "source"),
        "value": _plural(len(sources), "source"),
        "note": ", ".join(name for name, _ in sources.most_common(2)) + (" and more" if len(sources) > 2 else ""),
        "evidence": [{"name": name, "mentions": n} for name, n in sources.most_common(EVIDENCE_ROWS)],
    }

    # momentum
    dated = [i["occurred_at"] for i in items if isinstance(i.get("occurred_at"), datetime)]
    momentum: Dict[str, Any] = {"raw": 0.0, "display": "not enough dated feedback", "value": "no trend", "note": "not enough dated feedback", "evidence": [], "enough": False}
    if anchor is not None and dated:
        window = timedelta(days=MOMENTUM_WINDOW_DAYS)
        recent = sum(1 for d in dated if anchor - window < d <= anchor)
        previous = sum(1 for d in dated if anchor - 2 * window < d <= anchor - window)
        if recent + previous >= MIN_DATED_ITEMS:
            growth = (recent - previous) / (recent + previous)
            direction = "up" if growth > 0 else "down" if growth < 0 else "flat"
            momentum = {
                "raw": growth,
                "display": f"{recent} mentions in the last {MOMENTUM_WINDOW_DAYS} days vs {previous} before ({direction})",
                "value": {"up": "Rising", "down": "Falling", "flat": "Steady"}[direction],
                "note": f"{recent} in the last {MOMENTUM_WINDOW_DAYS} days vs {previous} before",
                "evidence": [
                    {"name": f"Last {MOMENTUM_WINDOW_DAYS} days", "mentions": recent},
                    {"name": f"Previous {MOMENTUM_WINDOW_DAYS} days", "mentions": previous},
                ],
                "enough": True,
            }

    # strategic
    customers = {k[1]: rows for k, rows in by_reporter.items() if k[0] == "customer"}
    enterprise = [cid for cid, rows in customers.items() if any((r.get("customer_tier") or "").lower() == "enterprise" for r in rows)]
    known_tier = any((r.get("customer_tier") or "free").lower() not in ("free", "") for rows in customers.values() for r in rows)
    strategic = {
        "raw": (len(enterprise) / len(customers)) if customers else 0.0,
        "display": f"{_plural(len(enterprise), 'enterprise account')} of {len(customers)}" if customers else "no named customers",
        "value": f"{len(enterprise)} of {len(customers)}" if customers else "none",
        "note": "customers on the enterprise tier",
        "evidence": [{"name": cid} for cid in enterprise[:EVIDENCE_ROWS]],
        "known": known_tier,
    }

    return {"reach": reach, "revenue": revenue, "urgency": urgency, "breadth": breadth, "momentum": momentum, "strategic": strategic}


# ---------------------------------------------------------------- scoring a whole project

def score_themes(
    themes: List[Dict[str, Any]],
    profile: str = DEFAULT_PROFILE,
    project_source_count: int = 0,
) -> List[Dict[str, Any]]:
    """
    themes: [{"key": ..., "items": [...], "cohesion": float, "verified_quotes": int}]
    Returns one breakdown per theme, in the same order, each with its priority and rank.
    """
    if profile not in PROFILES:
        profile = DEFAULT_PROFILE
    weights = PROFILES[profile]["weights"]

    all_dates = [i["occurred_at"] for t in themes for i in t["items"] if isinstance(i.get("occurred_at"), datetime)]
    anchor = max(all_dates) if all_dates else None
    raw = [compute_signals(t["items"], anchor) for t in themes]

    # decide, for the whole project, which signals can be used
    dropped: List[Dict[str, str]] = []
    active: List[str] = []
    for key in weights:
        if key == "revenue" and not any(r["revenue"]["raw"] > 0 for r in raw):
            dropped.append({"key": key, "label": SIGNAL_INFO[key]["label"], "short": "no ARR in the data", "reason": "No customer ARR in this project's data. Add an ARR column or a customer list to rank by revenue."})
        elif key == "breadth" and project_source_count < 2:
            dropped.append({"key": key, "label": SIGNAL_INFO[key]["label"], "short": "only one source", "reason": "Only one source in this project, so spread across sources says nothing."})
        elif key == "momentum" and not any(r["momentum"].get("enough") for r in raw):
            dropped.append({"key": key, "label": SIGNAL_INFO[key]["label"], "short": "no event dates", "reason": "Not enough feedback with real event dates to see a trend."})
        elif key == "strategic" and not any(r["strategic"].get("known") for r in raw):
            dropped.append({"key": key, "label": SIGNAL_INFO[key]["label"], "short": "no customer tiers", "reason": "No customer tiers in the data."})
        else:
            active.append(key)

    total_weight = sum(weights[k] for k in active) or 1.0
    effective = {k: weights[k] / total_weight for k in active}
    percentile = {k: _percentiles([r[k]["raw"] for r in raw]) for k in active}

    results: List[Dict[str, Any]] = []
    for idx, theme in enumerate(themes):
        signals = []
        priority = 0.0
        for key in active:
            # A theme with none of something (no churn talk, no revenue, a falling trend) earns nothing for it
            share = percentile[key][idx] if raw[idx][key]["raw"] > 0 else 0.0
            points = 100 * effective[key] * share
            priority += points
            info = SIGNAL_INFO[key]
            signals.append({
                "key": key,
                "label": info["label"],
                "raw": round(raw[idx][key]["raw"], 4),
                "display": raw[idx][key]["display"],
                "value": raw[idx][key]["value"],
                "note": raw[idx][key]["note"],
                "max_points": round(100 * effective[key], 2),
                "percentile": round(share, 3),
                "weight": round(effective[key], 4),
                "points": round(points, 2),
                "evidence": raw[idx][key]["evidence"],
                "why": info["why"],
                "how": info["how"],
            })
        verified = int(theme.get("verified_quotes", 0))
        mentions = len(theme["items"])
        results.append({
            "version": 1,
            "profile": profile,
            "profile_label": PROFILES[profile]["label"],
            "priority_score": round(priority, 2),
            "signals": signals,
            "dropped": dropped,
            "confidence": {
                "cohesion": round(float(theme.get("cohesion", 0.0)), 3),
                "verified_quotes": verified,
                "mentions": mentions,
                "level": "supported" if verified >= 2 and mentions >= 3 else "thin",
            },
        })

    order = sorted(range(len(results)), key=lambda i: -results[i]["priority_score"])
    for position, i in enumerate(order, start=1):
        results[i]["rank"] = position
        results[i]["of"] = len(results)
        results[i]["verdict"] = _verdict(results[i])
    return results


def _verdict(breakdown: Dict[str, Any]) -> str:
    """One sentence built from the numbers behind the score: top contributors first."""
    top = sorted(breakdown["signals"], key=lambda s: -s["points"])[:3]
    parts = [s["display"] for s in top if s["points"] > 0 and s["raw"] > 0]
    base = f"Ranked #{breakdown['rank']} of {breakdown['of']}"
    if parts:
        base += ": " + "; ".join(parts)
    if breakdown["confidence"]["level"] == "thin":
        base += ". Thin evidence: fewer than 2 verified quotes or 3 mentions"
    return base + "."
