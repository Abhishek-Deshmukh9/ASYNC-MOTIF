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
import re
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


# ---------------------------------------------------------------- issue types
# The kind of problem shifts the weights: final weight = base weight (company profile) x type multiplier,
# rescaled so the weights still add up to 1. The type comes from the customers' own words, never from a
# model, and the matching words are kept as evidence. A PM can change it, which re-ranks the project.
ISSUE_TYPES: Dict[str, Dict[str, Any]] = {
    "security": {
        "label": "Security",
        "phrases": ["security", "vulnerability", "vulnerable", "exploit", "breach", "leak", "leaked", "leaking",
                    "exposed", "exposure", "unauthorized", "unauthorised", "password", "credentials", "phishing",
                    "xss", "injection", "csrf", "2fa", "mfa", "hacked", "malicious"],
        "multipliers": {"reach": 1.4, "urgency": 1.3, "momentum": 2.0, "revenue": 0.6, "strategic": 0.8},
        "why": "A security problem is fixed before anything else, whatever its score: it is listed first.",
        "lane": "fix_first",
    },
    "bug": {
        "label": "Bug",
        "phrases": ["bug", "crash", "crashes", "crashed", "crashing", "error", "errors", "fails", "failed", "failing",
                    "failure", "broken", "breaks", "doesn't work", "does not work", "not working", "stopped working",
                    "times out", "timed out", "timeout", "time out", "freezes", "frozen", "hangs", "exception",
                    "data loss", "lost data", "silently", "drops", "truncates", "truncated", "wrong", "incorrect",
                    "slow", "lag", "laggy", "takes forever"],
        "multipliers": {"reach": 1.4, "urgency": 1.3, "momentum": 2.0, "revenue": 0.6, "strategic": 0.8},
        "why": "A bug costs more the more people hit it and the faster it spreads, whoever they are, so reach and momentum count more and revenue less.",
    },
    "ux": {
        "label": "UX friction",
        "phrases": ["confusing", "confused", "unclear", "hard to find", "can't find", "cannot find", "couldn't find",
                    "could not tell", "couldn't tell", "hard to", "difficult to", "not intuitive", "unintuitive",
                    "clunky", "too many clicks", "too many steps", "cluttered", "frustrating"],
        "multipliers": {"reach": 1.5, "breadth": 1.4, "revenue": 0.6, "strategic": 0.6},
        "why": "Friction matters by how widely it is felt, across people and channels, more than by who pays most.",
    },
    "feature": {
        "label": "Feature request",
        "phrases": ["please add", "would love", "wish", "feature request", "add support", "support for", "it would be great",
                    "would be nice", "we need", "missing", "can you add", "ability to", "integration", "integrate",
                    "no way to", "there is no", "doesn't have", "does not have", "looking at competitors"],
        "multipliers": {"revenue": 1.4, "strategic": 2.0, "breadth": 0.8, "momentum": 0.6, "urgency": 0.6},
        "why": "A feature request is an investment: who is asking (revenue, enterprise accounts) counts more than how fast mentions grow.",
    },
    "general": {
        "label": "General",
        "phrases": [],
        "multipliers": {},
        "why": "No clear kind of problem in the words used, so the base weights apply unchanged.",
    },
}
TYPE_ORDER = ["security", "bug", "ux", "feature"]   # tie-break: the more urgent kind wins
MIN_TYPE_SHARE = 0.3                                # at least 30% of the theme's messages must use the words


def _phrase_pattern(phrase: str) -> "re.Pattern[str]":
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")


_PATTERNS = {key: [(p, _phrase_pattern(p)) for p in spec["phrases"]] for key, spec in ISSUE_TYPES.items()}


def classify_issue(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The kind of problem a theme is, from the words its messages use, with those words as evidence."""
    hits: Dict[str, List[Dict[str, str]]] = {key: [] for key in TYPE_ORDER}
    for item in items:
        text = (item.get("content") or item.get("clean_content") or "").lower()
        if not text:
            continue
        for key in TYPE_ORDER:
            for phrase, pattern in _PATTERNS[key]:
                if pattern.search(text):
                    hits[key].append({"term": phrase, "text": _snippet(item.get("content") or text, 140), "name": _reporter_key(item)[1]})
                    break  # one hit per message per type
    total = len(items) or 1
    counts = {key: len(hits[key]) for key in TYPE_ORDER}
    best = max(TYPE_ORDER, key=lambda key: (counts[key], -TYPE_ORDER.index(key)))
    chosen = best if counts[best] / total >= MIN_TYPE_SHARE else "general"
    return _type_payload(chosen, source="words", counts=counts, total=len(items), evidence=hits.get(chosen, [])[:4])


def _type_payload(key: str, source: str, counts: Optional[Dict[str, int]] = None, total: int = 0, evidence: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    spec = ISSUE_TYPES[key]
    return {
        "type": key,
        "label": spec["label"],
        "source": source,                     # "words" (from the messages) or "pm" (changed by a person)
        "counts": counts or {},
        "messages": total,
        "evidence": evidence or [],
        "multipliers": spec["multipliers"],
        "why": spec["why"],
        "lane": spec.get("lane"),
    }


def type_weights(base: Dict[str, float], active: List[str], issue_type: str) -> Dict[str, float]:
    """w_k = base_k x multiplier_k(type), divided by the sum over the parameters in use."""
    multipliers = ISSUE_TYPES.get(issue_type, ISSUE_TYPES["general"])["multipliers"]
    adjusted = {k: base[k] * multipliers.get(k, 1.0) for k in active}
    total = sum(adjusted.values()) or 1.0
    return {k: v / total for k, v in adjusted.items()}


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

    percentile = {k: _percentiles([r[k]["raw"] for r in raw]) for k in active}
    type_table = {key: {k: round(w, 4) for k, w in type_weights(weights, active, key).items()} for key in ISSUE_TYPES}

    results: List[Dict[str, Any]] = []
    for idx, theme in enumerate(themes):
        issue = classify_issue(theme["items"])
        effective = type_weights(weights, active, issue["type"])
        signals = []
        for key in active:
            # A theme with none of something (no churn talk, no revenue, a falling trend) earns nothing for it
            share = percentile[key][idx] if raw[idx][key]["raw"] > 0 else 0.0
            info = SIGNAL_INFO[key]
            signals.append({
                "key": key,
                "label": info["label"],
                "raw": round(raw[idx][key]["raw"], 4),
                "display": raw[idx][key]["display"],
                "value": raw[idx][key]["value"],
                "note": raw[idx][key]["note"],
                "percentile": round(share, 3),
                "evidence": raw[idx][key]["evidence"],
                "why": info["why"],
                "how": info["how"],
            })
        verified = int(theme.get("verified_quotes", 0))
        mentions = len(theme["items"])
        breakdown = {
            "version": 2,
            "profile": profile,
            "profile_label": PROFILES[profile]["label"],
            "base_weights": {k: weights[k] for k in active},
            "type_table": type_table,
            "issue_type": issue,
            "signals": signals,
            "dropped": dropped,
            "confidence": {
                "cohesion": round(float(theme.get("cohesion", 0.0)), 3),
                "verified_quotes": verified,
                "mentions": mentions,
                "level": "supported" if verified >= 2 and mentions >= 3 else "thin",
            },
        }
        _apply_weights(breakdown, effective)
        results.append(breakdown)

    rank_breakdowns(results)
    return results


def _apply_weights(breakdown: Dict[str, Any], effective: Dict[str, float]) -> None:
    """Points for each parameter = 100 x weight x its 0..1 value; the score is their sum."""
    priority = 0.0
    for signal in breakdown["signals"]:
        weight = effective.get(signal["key"], 0.0)
        points = 100 * weight * signal["percentile"]
        signal["weight"] = round(weight, 4)
        signal["max_points"] = round(100 * weight, 2)
        signal["points"] = round(points, 2)
        priority += points
    breakdown["priority_score"] = round(priority, 2)


def rank_breakdowns(results: List[Dict[str, Any]]) -> None:
    """Security problems first (Fix first), then everything else by score."""
    def lane(b: Dict[str, Any]) -> int:
        return 0 if (b.get("issue_type") or {}).get("lane") == "fix_first" else 1
    order = sorted(range(len(results)), key=lambda i: (lane(results[i]), -results[i]["priority_score"]))
    for position, i in enumerate(order, start=1):
        results[i]["rank"] = position
        results[i]["of"] = len(results)
        results[i]["lane"] = "fix_first" if lane(results[i]) == 0 else "ranked"
        results[i]["verdict"] = _verdict(results[i])


def retype_breakdowns(results: List[Dict[str, Any]], index: int, new_type: str) -> None:
    """A PM changed one theme's kind of problem: re-weight that theme from its stored values and re-rank all."""
    if new_type not in ISSUE_TYPES:
        raise ValueError(f"Unknown issue type: {new_type}")
    breakdown = results[index]
    base = breakdown.get("base_weights") or {s["key"]: s["weight"] for s in breakdown["signals"]}
    active = [s["key"] for s in breakdown["signals"]]
    previous = breakdown.get("issue_type") or {}
    breakdown["issue_type"] = _type_payload(new_type, source="pm", counts=previous.get("counts"), total=previous.get("messages", 0))
    breakdown["issue_type"]["detected"] = previous.get("detected") or previous.get("type")
    _apply_weights(breakdown, type_weights(base, active, new_type))
    rank_breakdowns(results)


def _verdict(breakdown: Dict[str, Any]) -> str:
    """One sentence built from the numbers behind the score: top contributors first."""
    top = sorted(breakdown["signals"], key=lambda s: -s["points"])[:3]
    parts = [s["display"] for s in top if s["points"] > 0 and s["raw"] > 0]
    issue = breakdown.get("issue_type") or {}
    base = f"Ranked #{breakdown['rank']} of {breakdown['of']}"
    if breakdown.get("lane") == "fix_first":
        base += " (security, fixed first)"
    elif issue.get("type") and issue.get("type") != "general":
        base += " as " + {"bug": "a bug", "ux": "UX friction", "feature": "a feature request"}.get(issue["type"], issue["label"].lower())
    if parts:
        base += ": " + "; ".join(parts)
    if breakdown["confidence"]["level"] == "thin":
        base += ". Thin evidence: fewer than 2 verified quotes or 3 mentions"
    return base + "."
