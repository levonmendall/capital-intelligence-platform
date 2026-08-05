"""Plain-language, lineage-safe reader view for a CIO decision export.

Presentation only. The module selects persisted records for one decision, derives a
concise explanation, and serializes a read-only bundle. It cannot change investment
analysis, sizing, construction, execution, or real-money authority.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping

from cio_decision_export import select_cio_decision_records


_SCHEMA_VERSION = "cio-decision-export.v3"
_HISTORY_LIMIT = 500
_NO_CHANGE = frozenset(
    {"hold", "watch", "insufficient_evidence", "no_superior_opportunity", "no_material_change"}
)
_BUY = frozenset({"buy", "increase", "add", "initiate"})
_REDUCE = frozenset({"reduce", "sell", "exit", "close"})


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _record(bundle: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    records = bundle.get("records")
    return _mapping(records.get(name)) if isinstance(records, Mapping) else None


def _number(record: Mapping[str, Any] | None, *names: str) -> float | None:
    if not isinstance(record, Mapping):
        return None
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result = float(value)
            if result == result and result not in {float("inf"), float("-inf")}:
                return result
    return None


def _values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_clean(value),) if _clean(value) else ()
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return tuple(_clean(item) for item in value if _clean(item))
    return ()


def _unique(values: Iterable[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold().strip(" .,;:–—-")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) == limit:
            break
    return result


def _sentence(value: object) -> str:
    text = _clean(value)
    return text if not text or text[-1:] in {".", "!", "?"} else text + "."


def _capitalize(value: object) -> str:
    text = _clean(value)
    return text[:1].upper() + text[1:] if text else text


def _symbol_from_identifier(value: object) -> str:
    match = re.search(r"(?:candidate|holding):([A-Za-z0-9.-]+)(?::|$)", _clean(value))
    return "" if match is None else match.group(1).upper()


def _symbol(*records: Mapping[str, Any] | None) -> str:
    for record in records:
        if not isinstance(record, Mapping):
            continue
        direct = _clean(record.get("symbol")).upper()
        if direct:
            return direct
        for name in ("candidate_symbol", "candidate_identifier", "best_alternative_identifier"):
            inferred = _symbol_from_identifier(record.get(name))
            if inferred:
                return inferred
    return "the leading opportunity"


def _plain(value: object, symbol: str) -> str:
    text = _clean(value)
    replacements = (
        (r"\bCIO decision:\s*", ""),
        (r"\bno material change\b", "no portfolio change"),
        (r"\bNo executable portfolio change is proposed\b", "No trade is proposed"),
        (r"\bcost-adjusted expected return\b", "estimated return after costs"),
        (r"\bopportunity edge\b", "estimated advantage over the next-best option"),
        (r"\bhysteresis\b", "required confirmation period"),
        (r"\bcandidate\b", symbol or "opportunity"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return _clean(text)


def _action(
    bundle: Mapping[str, Any],
    briefing: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
    symbol: str,
) -> tuple[str, str]:
    actions = bundle.get("decision_actions")
    actions = actions if isinstance(actions, Mapping) else {}
    selected = _clean(actions.get("selected_action")).lower().replace(" ", "_")
    effective = _clean(actions.get("effective_action")).lower().replace(" ", "_")
    if decision is None:
        briefing_action = _plain(
            briefing.get("portfolio_decision")
            if isinstance(briefing, Mapping)
            else None,
            symbol,
        )
        if briefing_action:
            return (
                "Briefing reports the current portfolio action",
                _capitalize(briefing_action)
                + " The detailed CIO decision record could not be aligned, so this "
                "statement should be treated as a briefing-only explanation.",
            )
        return (
            "Decision export is incomplete",
            "The portfolio action cannot be verified from the records in this file.",
        )
    if bool(actions.get("deferred")) and selected and selected != effective:
        preferred = (
            f"reduce {symbol}"
            if selected in _REDUCE
            else f"increase {symbol}"
            if selected in _BUY
            else selected.replace("_", " ")
        )
        return (
            "No immediate portfolio change",
            f"The CIO prefers to {preferred}, but the portfolio remains unchanged because the required confirmation or waiting period is still active.",
        )
    if not effective or effective in _NO_CHANGE:
        return "No portfolio change", f"The CIO reviewed {symbol} and kept the portfolio unchanged."
    if effective in _BUY:
        return (
            f"Paper purchase of {symbol} approved",
            f"The CIO approved increasing {symbol}, subject to aligned construction and paper-implementation controls.",
        )
    if effective in _REDUCE:
        return (
            f"Reduction of {symbol} approved",
            f"The CIO approved reducing {symbol}, subject to aligned construction and paper-implementation controls.",
        )
    return "CIO decision recorded", _sentence(effective.replace("_", " "))


def _percent_match(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return None
    try:
        return float(match.group(1)) / 100.0
    except (TypeError, ValueError):
        return None


def _briefing_number_fallbacks(
    briefing: Mapping[str, Any] | None,
) -> dict[str, float | int | None]:
    if not isinstance(briefing, Mapping):
        return {}
    why = _clean(briefing.get("why_it_matters"))
    developments = " ".join(_values(briefing.get("material_developments")))
    opportunity = _clean(briefing.get("opportunity_or_risk"))
    rank_match = re.search(r"ranked\s*#(\d+)", opportunity, flags=re.IGNORECASE)
    return {
        "expected": _percent_match(
            why,
            r"offers\s+(?:an?\s+)?([-+]?\d+(?:\.\d+)?)%[^.]*return",
        ),
        "alternative": _percent_match(
            why,
            r"versus\s+(?:an?\s+)?([-+]?\d+(?:\.\d+)?)%",
        ),
        "downside": _percent_match(
            why,
            r"(?:with\s+)?([-+]?\d+(?:\.\d+)?)%\s+expected downside",
        ),
        "edge": _percent_match(
            developments,
            r"opportunity edge is\s+([-+]?\d+(?:\.\d+)?)%",
        ),
        "rank": int(rank_match.group(1)) if rank_match is not None else None,
    }


def _key_numbers(
    briefing: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expected = _number(evidence, "expected_return", "reconciled_expected_return")
    expected = expected if expected is not None else _number(decision, "expected_return")
    alternative = _number(evidence, "effective_opportunity_cost", "baseline_opportunity_cost")
    alternative = alternative if alternative is not None else _number(decision, "effective_opportunity_cost")
    edge = _number(evidence, "opportunity_edge", "cash_relative_edge")
    if edge is None and expected is not None and alternative is not None:
        edge = expected - alternative
    downside = _number(evidence, "expected_downside", "reconciled_downside")
    downside = downside if downside is not None else _number(decision, "expected_downside")
    probability = _number(evidence, "reconciled_probability_of_success", "probability_of_success")
    probability = probability if probability is not None else _number(decision, "probability_of_success")
    confidence = _number(briefing, "confidence")
    confidence = confidence if confidence is not None else _number(decision, "final_confidence", "confidence")
    rank = evidence.get("opportunity_rank") if isinstance(evidence, Mapping) else None
    fallback = _briefing_number_fallbacks(briefing)
    expected = expected if expected is not None else fallback.get("expected")
    alternative = alternative if alternative is not None else fallback.get("alternative")
    edge = edge if edge is not None else fallback.get("edge")
    downside = downside if downside is not None else fallback.get("downside")
    rank = rank if isinstance(rank, int) and not isinstance(rank, bool) else fallback.get("rank")
    if edge is None and expected is not None and alternative is not None:
        edge = expected - alternative
    return {
        "estimated_return_after_costs": expected,
        "next_best_option_return": alternative,
        "estimated_advantage": edge,
        "estimated_downside": downside,
        "estimated_success_probability": probability,
        "decision_confidence": confidence,
        "opportunity_rank": rank if isinstance(rank, int) and not isinstance(rank, bool) else None,
    }


def _number_sentences(numbers: Mapping[str, Any]) -> list[str]:
    expected = numbers.get("estimated_return_after_costs")
    alternative = numbers.get("next_best_option_return")
    edge = numbers.get("estimated_advantage")
    downside = numbers.get("estimated_downside")
    probability = numbers.get("estimated_success_probability")
    confidence = numbers.get("decision_confidence")
    result: list[str] = []
    if isinstance(expected, float) and isinstance(alternative, float):
        result.append(f"The model estimates a {expected:.1%} return after costs, compared with {alternative:.1%} for the next-best option.")
    elif isinstance(expected, float):
        result.append(f"The model estimates a {expected:.1%} return after costs.")
    if isinstance(edge, float):
        direction = "advantage" if edge >= 0 else "disadvantage"
        result.append(f"That is an estimated {direction} of {abs(edge) * 100:.1f} percentage points.")
    if isinstance(downside, float):
        result.append(f"Estimated downside in an adverse outcome is {abs(downside):.1%}.")
    if isinstance(probability, float):
        result.append(f"The estimated probability of a positive outcome is {probability:.1%}.")
    if isinstance(confidence, float):
        result.append(f"Decision confidence is {confidence:.1%}; it reflects evidence quality, not a guaranteed return.")
    return result


def _reasons(briefing: Mapping[str, Any] | None, numbers: Mapping[str, Any], symbol: str) -> list[str]:
    values: list[str] = []
    rank = numbers.get("opportunity_rank")
    if isinstance(rank, int):
        values.append(f"{symbol} ranked #{rank} among the evaluated opportunities.")
    changed = _clean(briefing.get("what_changed") if isinstance(briefing, Mapping) else None)
    if changed:
        values.append(
            "Updated company fundamentals, valuation, price trend, and economic conditions changed the return estimate."
            if "quality, growth, valuation, momentum, and regime" in changed.lower()
            else _sentence(_plain(changed, symbol))
        )
    opportunity = _clean(
        briefing.get("opportunity_or_risk")
        if isinstance(briefing, Mapping)
        else None
    )
    opportunity_reason = opportunity.split(";", 1)[0].strip()
    if opportunity_reason and "ranked #" not in opportunity_reason.casefold():
        values.append(_sentence(_plain(opportunity_reason, symbol)))
    return _unique(values, 4)


def _simplify_risk(value: object, symbol: str) -> str:
    text = _clean(value)
    exact = {
        "analytical coverage is incomplete": "Some analytical coverage is incomplete.",
        "earnings_quality support is limited": "Evidence about earnings quality is limited.",
        "regime_fit support is limited": "Evidence that the opportunity fits the current economic regime is limited.",
        "company_risk evidence is unfavorable": "Company-specific risk evidence is unfavorable.",
    }
    if text.casefold().strip(" .") in exact:
        return exact[text.casefold().strip(" .")]
    patterns = (
        (r"Realized annualized volatility=([-+]?\d+(?:\.\d+)?)%", "Recent annualized volatility is {v}%.", False),
        (r"Maximum historical drawdown=([-+]?\d+(?:\.\d+)?)%", "The historical maximum drawdown is {v}%.", True),
        (r"Probability of a material path drawdown is ([-+]?\d+(?:\.\d+)?)%", "The model estimates a {v}% chance of a material drawdown.", False),
    )
    for pattern, template, absolute in patterns:
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match:
            value = abs(float(match.group(1))) if absolute else float(match.group(1))
            return template.format(v=f"{value:.1f}")
    return _sentence(_plain(text, symbol))


def _risks(
    briefing: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None,
    symbol: str,
) -> list[str]:
    raw: list[str] = []
    opportunity = _clean(briefing.get("opportunity_or_risk") if isinstance(briefing, Mapping) else None)
    match = re.search(r"; the central risk is (.+)", opportunity, flags=re.IGNORECASE)
    if match:
        raw.append(match.group(1))
    dissent = decision.get("dissent") if isinstance(decision, Mapping) else None
    if isinstance(dissent, Mapping) and _clean(dissent.get("opposing_conclusion")):
        raw.append("One specialist disagreed: " + _clean(dissent.get("opposing_conclusion")))
    for record in (evidence, decision):
        if isinstance(record, Mapping):
            raw.extend(_values(record.get("risks")))
            raw.extend(_values(record.get("contradictory_evidence")))
    priority = ("drawdown", "volatility", "incomplete", "limited", "unfavorable")
    ordered = sorted(enumerate(raw), key=lambda item: (not any(term in item[1].lower() for term in priority), item[0]))
    return _unique((_simplify_risk(value, symbol) for _, value in ordered), 5)


def _watch(briefing: Mapping[str, Any] | None, decision: Mapping[str, Any] | None, symbol: str) -> list[str]:
    exact = {
        "expected return falls below the opportunity qualification threshold": "The estimated return falls below the required minimum.",
        "evidence quality or freshness falls below policy": "The evidence becomes stale or less reliable.",
        "a qualified replacement offers a materially superior opportunity edge": "A clearly better investment becomes available.",
        "reclassify when long yields, curve shape, policy rates, or vix change materially": "Interest rates, the yield curve, policy, or market volatility change materially.",
        "refresh after new sec filings, a relative-strength reversal, or a material macro change": "New company filings, a reversal in relative performance, or a major economic change.",
        "the company remains in the daily broad-equity discovery set": "The company stops qualifying for the daily investable-company screen.",
        "execution receives a current positive non-crossed quote": "A current executable market quote becomes unavailable.",
        "capital-flow direction and persistence do not reverse before implementation": "Market participation and capital-flow direction reverse before implementation.",
        "the expectations gap remains positive after refreshed price, volatility, and candidate evidence": "Updated price, volatility, or company evidence removes the expected-return advantage.",
    }
    raw: list[str] = []
    if isinstance(briefing, Mapping):
        raw.extend(_values(briefing.get("evidence_that_changes_conclusion")))
    if isinstance(decision, Mapping):
        raw.extend(_values(decision.get("invalidation_conditions")))
    simplified = (
        exact.get(value.casefold().strip(" ."), _sentence(_plain(value, symbol)))
        for value in raw
    )
    return _unique(simplified, 6)


def _audit(bundle: Mapping[str, Any]) -> tuple[str, str]:
    audit = bundle.get("auditability")
    audit = audit if isinstance(audit, Mapping) else {}
    if _clean(audit.get("status")) == "auditable":
        return (
            "complete",
            "The detailed records below belong to the same decision lineage.",
        )
    labels = {
        "cio_decision:code_version_not_recorded": (
            "the software version used for the decision was not recorded"
        ),
        "cio_decision:missing_for_decision": (
            "the matching detailed CIO decision record is missing"
        ),
        "decision_evidence_snapshot:missing_for_decision": (
            "the matching evidence snapshot is missing"
        ),
        "portfolio_construction:lineage_unproven": (
            "the available construction record belongs to another or unproven cycle"
        ),
        "portfolio_construction:missing_for_executable_action": (
            "an executable decision lacks matching portfolio construction"
        ),
    }
    issues = [
        labels.get(issue, issue.replace("_", " ").replace(":", ": "))
        for issue in _values(audit.get("issues"))
    ]
    detail = "; ".join(issues) or "record alignment could not be verified"
    return (
        "incomplete",
        "This file is not a complete verified decision memo because " + detail + ".",
    )


def build_reader_summary(bundle: Mapping[str, Any], *, current_market_context: object = None) -> dict[str, Any]:
    """Derive a generic explanation from the aligned governed records."""

    briefing = _record(bundle, "daily_cio_briefing")
    decision = _record(bundle, "cio_decision")
    evidence = _record(bundle, "decision_evidence_snapshot")
    symbol = _symbol(evidence, decision, briefing)
    headline, portfolio_action = _action(bundle, briefing, decision, symbol)
    numbers = _key_numbers(briefing, decision, evidence)
    risks = _risks(briefing, decision, evidence, symbol)
    status, audit_note = _audit(bundle)
    market_summary = _plain(current_market_context, symbol)
    if not market_summary and isinstance(briefing, Mapping):
        market_summary = _clean(
            briefing.get("market_backdrop")
            or briefing.get("current_backdrop")
            or briefing.get("environment_summary")
            or briefing.get("market_environment")
        )
    parts = [portfolio_action, *_number_sentences(numbers)]
    if risks:
        parts.append("Main concern: " + risks[0])
    if status != "complete":
        parts.insert(0, audit_note)
    return {
        "status": status,
        "headline": headline,
        "summary": " ".join(_sentence(part) for part in parts if _clean(part)),
        "portfolio_action": portfolio_action,
        "why": _reasons(briefing, numbers, symbol),
        "key_numbers": numbers,
        "main_risks": risks,
        "what_would_change_the_decision": _watch(briefing, decision, symbol),
        "current_market_context": {
            "scope": "current_at_export_time",
            "summary": market_summary or "Current market context was unavailable when this export was generated.",
        },
        "audit_note": audit_note,
        "language": "plain_english",
    }


def enrich_cio_decision_export(bundle: Mapping[str, Any], *, current_market_context: object = None) -> dict[str, Any]:
    """Place the reader summary before the unchanged technical records."""

    result: dict[str, Any] = {
        "reader_summary": build_reader_summary(
            bundle,
            current_market_context=current_market_context,
        ),
        "schema_version": _SCHEMA_VERSION,
    }
    result.update({str(key): value for key, value in bundle.items() if key != "schema_version"})
    return result


def cio_decision_reader_json(bundle: Mapping[str, Any]) -> str:
    """Serialize in insertion order so the readable summary appears first."""

    return json.dumps(dict(bundle), indent=2, sort_keys=False, ensure_ascii=False, allow_nan=False) + "\n"


def _history(app: object, event_type: str, provided: Mapping[str, Any] | None = None) -> tuple[Mapping[str, Any], ...]:
    values: list[Mapping[str, Any]] = [provided] if isinstance(provided, Mapping) else []
    loader = getattr(app, "_history", None)
    if callable(loader):
        try:
            history = loader(event_type, limit=_HISTORY_LIMIT)
        except (OSError, RuntimeError, TypeError, ValueError):
            history = ()
        if isinstance(history, Iterable) and not isinstance(history, (str, bytes, Mapping)):
            values.extend(item for item in history if isinstance(item, Mapping))
    latest = getattr(app, "_latest", None)
    if callable(latest):
        try:
            record = latest(event_type)
        except (OSError, RuntimeError, TypeError, ValueError):
            record = None
        if isinstance(record, Mapping):
            values.append(record)
    return tuple(values)


def select_report_records(
    app: object,
    *,
    daily_cio_briefing: Mapping[str, Any] | None,
    portfolio_construction: Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any] | None]:
    """Select the exact decision lineage instead of combining latest event types."""

    return select_cio_decision_records(
        daily_cio_briefing=daily_cio_briefing,
        cio_decisions=_history(app, "cio_decision"),
        decision_evidence_snapshots=_history(app, "decision_evidence_snapshot"),
        portfolio_constructions=_history(app, "portfolio_construction", portfolio_construction),
        decision_evaluations=_history(app, "decision_evaluation"),
    )


__all__ = [
    "build_reader_summary",
    "cio_decision_reader_json",
    "enrich_cio_decision_export",
    "select_report_records",
]
