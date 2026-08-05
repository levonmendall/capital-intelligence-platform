"""Render one exact-lineage CIO decision as a plain-language investment memo.

This module is presentation-only. It receives the read-only bundle already selected
by the CIO report export path and cannot collect evidence, rank candidates, change a
CIO action, size a position, construct a portfolio, or authorize execution.
"""

from __future__ import annotations

import re
from html import escape
from types import ModuleType
from typing import Any, Mapping, Sequence


_CSS = """
<style>
.cio-memo-shell { margin: .75rem 0 1.15rem; }
.cio-memo-hero {
    padding: 1rem 1.05rem;
    border: 1px solid rgba(var(--surface-rgb), .30);
    border-radius: 1.05rem;
    background: linear-gradient(145deg, rgba(13,20,34,.97), rgba(8,13,24,.97));
    box-shadow: inset 0 1px 0 rgba(255,255,255,.05), 0 18px 42px rgba(0,0,0,.20);
}
.cio-memo-kicker {
    color: var(--surface-accent);
    font-size: .64rem;
    font-weight: 850;
    letter-spacing: .10em;
    text-transform: uppercase;
}
.cio-memo-title {
    margin-top: .34rem;
    color: #f4f7fc;
    font-size: 1.28rem;
    line-height: 1.25;
    font-weight: 820;
}
.cio-memo-summary {
    margin-top: .55rem;
    color: #bac6d7;
    font-size: .84rem;
    line-height: 1.62;
}
.cio-memo-action-row {
    display: flex;
    flex-wrap: wrap;
    gap: .48rem;
    margin-top: .72rem;
}
.cio-memo-pill {
    display: inline-flex;
    align-items: center;
    min-height: 2rem;
    padding: .34rem .62rem;
    border: 1px solid rgba(var(--surface-rgb), .34);
    border-radius: 999px;
    background: rgba(var(--surface-rgb), .10);
    color: #e9eef7;
    font-size: .68rem;
    font-weight: 780;
}
.cio-memo-metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: .55rem;
    margin-top: .62rem;
}
.cio-memo-metric {
    padding: .72rem .76rem;
    border: 1px solid rgba(138,157,188,.17);
    border-radius: .86rem;
    background: rgba(255,255,255,.018);
}
.cio-memo-metric-label {
    color: #8290a5;
    font-size: .60rem;
    font-weight: 800;
    letter-spacing: .07em;
    text-transform: uppercase;
}
.cio-memo-metric-value {
    margin-top: .28rem;
    color: #f1f5fb;
    font-size: .96rem;
    font-weight: 820;
}
.cio-memo-metric-note {
    margin-top: .20rem;
    color: #8391a7;
    font-size: .61rem;
    line-height: 1.35;
}
.cio-memo-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: .62rem;
    margin-top: .62rem;
}
.cio-memo-card {
    padding: .82rem .86rem;
    border: 1px solid rgba(138,157,188,.17);
    border-radius: .92rem;
    background: rgba(255,255,255,.018);
}
.cio-memo-card-wide { grid-column: 1 / -1; }
.cio-memo-card-title {
    color: #f0f4fa;
    font-size: .76rem;
    font-weight: 820;
}
.cio-memo-card-body {
    margin-top: .38rem;
    color: #b6c2d4;
    font-size: .73rem;
    line-height: 1.55;
}
.cio-memo-list {
    margin: .42rem 0 0;
    padding: 0;
    list-style: none;
}
.cio-memo-list li {
    position: relative;
    margin-top: .34rem;
    padding-left: .86rem;
    color: #aebbd0;
    font-size: .70rem;
    line-height: 1.48;
}
.cio-memo-list li::before {
    content: "";
    position: absolute;
    left: 0;
    top: .48rem;
    width: .32rem;
    height: .32rem;
    border-radius: 999px;
    background: var(--surface-accent);
    opacity: .82;
}
.cio-memo-audit {
    margin-top: .62rem;
    padding: .68rem .76rem;
    border: 1px solid rgba(138,157,188,.14);
    border-radius: .82rem;
    color: #8795aa;
    font-size: .62rem;
    line-height: 1.5;
    overflow-wrap: anywhere;
}
@media (max-width: 760px) {
    .cio-memo-hero { padding: .86rem .88rem; }
    .cio-memo-title { font-size: 1.08rem; }
    .cio-memo-summary { font-size: .78rem; }
    .cio-memo-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .cio-memo-grid { grid-template-columns: 1fr; }
    .cio-memo-card-wide { grid-column: auto; }
}
</style>
"""


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _first_text(
    *values: object,
    fallback: str = "Not separately recorded for this decision.",
) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return fallback


def _humanize_item(value: object) -> str:
    text = _clean(value)
    score = re.fullmatch(r"([a-zA-Z_ ]+) score=([+-]?[0-9.]+)", text)
    if score:
        label = score.group(1).replace("_", " ").strip().title()
        try:
            number = float(score.group(2))
        except ValueError:
            return text
        return f"{label} evidence scored {number:.0%}."
    return re.sub(r"\s*=\s*", " is ", text)


def _items(value: object, *, limit: int = 5) -> tuple[str, ...]:
    if isinstance(value, str):
        text = _clean(value)
        return (text,) if text else ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _humanize_item(item)
        key = text.casefold().strip(" .,;:–—-")
        if text and key not in seen:
            seen.add(key)
            output.append(text)
        if len(output) >= limit:
            break
    return tuple(output)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _percent(value: object, *, signed: bool = False) -> str:
    number = _number(value)
    if number is None:
        return "Not recorded"
    return f"{number:+.1%}" if signed else f"{number:.1%}"


def _title(value: object, fallback: str = "Not recorded") -> str:
    text = _clean(value)
    return text.replace("_", " ").title() if text else fallback


def _symbol_from_identifier(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].lower() in {
        "candidate",
        "holding",
        "instrument",
    }:
        likely = parts[1] if parts[0].lower() != "instrument" else parts[-1]
        if likely.lower() in {
            "us-equity",
            "us_etf",
            "us-equity-company",
        } and len(parts) >= 3:
            likely = parts[2]
        return likely.upper()
    return text


def _record_bundle(bundle: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    records = _mapping(bundle.get("records"))
    return (
        _mapping(records.get("cio_decision")),
        _mapping(records.get("daily_cio_briefing")),
        _mapping(records.get("decision_evidence_snapshot")),
        _mapping(records.get("portfolio_construction")),
        _mapping(records.get("decision_evaluation")),
    )


def _reconciliation(
    decision: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = decision.get("return_reconciliation")
    if isinstance(value, Mapping):
        return value
    value = evidence.get("return_reconciliation")
    return value if isinstance(value, Mapping) else {}


def _candidate_symbol(
    decision: Mapping[str, Any],
    briefing: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> str:
    return _first_text(
        decision.get("symbol"),
        evidence.get("symbol"),
        _symbol_from_identifier(decision.get("candidate_identifier")),
        _symbol_from_identifier(evidence.get("candidate_identifier")),
        _symbol_from_identifier(briefing.get("candidate_identifier")),
        fallback="Current opportunity",
    )


def _target_weight(construction: Mapping[str, Any], symbol: str) -> float | None:
    targets = construction.get("target_weights")
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
        return None
    for item in targets:
        if not isinstance(item, Mapping):
            continue
        if _clean(item.get("symbol")).upper() != symbol.upper():
            continue
        return _number(item.get("weight"))
    return None


def _trade_summary(construction: Mapping[str, Any]) -> str:
    trades = construction.get("trades")
    if (
        not isinstance(trades, Sequence)
        or isinstance(trades, (str, bytes))
        or not trades
    ):
        return "No exact-lineage paper transaction is proposed."
    descriptions: list[str] = []
    for item in trades[:4]:
        if not isinstance(item, Mapping):
            continue
        side = _title(item.get("side"), "Trade")
        symbol = _first_text(item.get("symbol"), fallback="instrument")
        weight = _percent(item.get("trade_weight"))
        descriptions.append(f"{side} {symbol} by {weight}")
    return (
        "; ".join(descriptions) + "."
        if descriptions
        else "A paper transaction is recorded."
    )


def _best_alternative(
    decision: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> str:
    value = _first_text(
        decision.get("best_alternative_identifier"),
        evidence.get("best_alternative_identifier"),
        fallback="cash and other qualified alternatives",
    )
    return _symbol_from_identifier(value) or value


def _extract_named_percent(text: object, label: str) -> float | None:
    source = _clean(text)
    match = re.search(
        rf"{re.escape(label)}\s+(?:is\s+)?([+-]?[0-9]+(?:\.[0-9]+)?)%",
        source,
        re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        return float(match.group(1)) / 100.0
    except ValueError:
        return None


def _committee_view(
    decision: Mapping[str, Any],
) -> tuple[str, tuple[str, ...]]:
    dissent = _mapping(decision.get("dissent"))
    opposing = _first_text(
        dissent.get("opposing_conclusion"),
        fallback="No separate material specialist dissent was recorded.",
    )
    support = _items(decision.get("catalysts"), limit=4)
    return opposing, support


def _implementation_reason(
    decision: Mapping[str, Any],
    construction: Mapping[str, Any],
    actions: Mapping[str, Any],
) -> str:
    selected = _title(actions.get("selected_action"))
    effective = _title(actions.get("effective_action"))
    if bool(actions.get("deferred")):
        return (
            f"The CIO selected {selected}, but the effective action remains {effective} "
            "because governed persistence or cooldown controls have not released the change."
        )
    blocks = _items(decision.get("implementation_blocks"), limit=3)
    if blocks:
        return "Implementation is blocked: " + "; ".join(blocks) + "."
    return _trade_summary(construction)


def build_investment_memo(
    bundle: Mapping[str, Any],
    *,
    market_backdrop: str = "",
    portfolio_posture: str = "",
) -> dict[str, Any]:
    """Build a concise investment-committee memo from one decision lineage."""

    decision, briefing, evidence, construction, _evaluation = _record_bundle(bundle)
    actions = dict(_mapping(bundle.get("decision_actions")))
    if not actions.get("effective_action"):
        actions["effective_action"] = decision.get("action")
    if not actions.get("selected_action"):
        deferred_action = _clean(decision.get("deferred_action"))
        actions["selected_action"] = (
            deferred_action
            if bool(decision.get("hysteresis_applied")) and deferred_action
            else decision.get("action")
        )
    if "deferred" not in actions:
        actions["deferred"] = bool(
            _clean(actions.get("selected_action"))
            and _clean(actions.get("effective_action"))
            and _clean(actions.get("selected_action"))
            != _clean(actions.get("effective_action"))
        )

    reconciliation = _reconciliation(decision, evidence)
    symbol = _candidate_symbol(decision, briefing, evidence)
    alternative = _best_alternative(decision, evidence)
    selected_action = _title(actions.get("selected_action") or decision.get("action"))
    effective_action = _title(actions.get("effective_action") or decision.get("action"))
    conclusion = _first_text(
        briefing.get("portfolio_decision"),
        decision.get("rationale"),
        decision.get("explanation"),
        fallback="No CIO conclusion was recorded for this decision.",
    )
    raw_rationale = _first_text(
        decision.get("rationale"),
        briefing.get("why_it_matters"),
        decision.get("opportunity_cost"),
    )
    what_changed = _first_text(
        briefing.get("what_changed"),
        decision.get("catalysts"),
    )
    backdrop_text = _first_text(
        market_backdrop,
        briefing.get("market_backdrop"),
        fallback=(
            "The report did not record a separate plain-language market backdrop."
        ),
    )

    candidate_return = _number(decision.get("expected_return"))
    if candidate_return is None:
        candidate_return = _number(reconciliation.get("expected_return"))
    alternative_return = _number(decision.get("effective_opportunity_cost"))
    if alternative_return is None:
        alternative_return = _number(evidence.get("effective_opportunity_cost"))
    downside = _number(reconciliation.get("expected_downside"))
    if downside is None:
        downside = _number(evidence.get("expected_downside"))
    success_probability = _number(reconciliation.get("probability_of_success"))
    if success_probability is None:
        success_probability = _number(evidence.get("probability_of_success"))
    confidence = _number(decision.get("final_confidence"))
    if confidence is None:
        confidence = _number(briefing.get("confidence"))

    opportunity_text = _first_text(
        decision.get("opportunity_cost"),
        decision.get("rationale"),
        fallback="",
    )
    robust_edge = _extract_named_percent(opportunity_text, "robust edge")
    stressed_edge = _extract_named_percent(opportunity_text, "stressed edge")
    current_weight = _number(evidence.get("current_portfolio_weight"))
    target_weight = _target_weight(construction, symbol)

    opposing_case, supportive_drivers = _committee_view(decision)
    bear_points = _items(decision.get("contradictory_evidence"), limit=5)
    if not bear_points:
        bear_points = _items(decision.get("risks"), limit=5)
    assumptions = _items(decision.get("key_assumptions"), limit=5)
    invalidation = _items(decision.get("invalidation_conditions"), limit=6)
    if not invalidation:
        invalidation = _items(
            briefing.get("evidence_that_changes_conclusion"),
            limit=6,
        )
    catalysts = _items(decision.get("catalysts"), limit=5)
    portfolio_impact = _first_text(
        decision.get("portfolio_impact"),
        briefing.get("portfolio_impact"),
        _trade_summary(construction),
    )
    funding = _first_text(
        decision.get("funding_source"),
        evidence.get("funding_source"),
        fallback=(
            "No funding source is required unless an executable change is released."
        ),
    )

    rationale_parts: list[str] = []
    if candidate_return is not None and alternative_return is not None:
        relationship = "above" if candidate_return >= alternative_return else "below"
        rationale_parts.append(
            f"{symbol}'s reconciled expected return is {_percent(candidate_return)}, "
            f"{relationship} {alternative}'s {_percent(alternative_return)} before the "
            "full uncertainty and downside stress is applied."
        )
    if robust_edge is not None or stressed_edge is not None:
        edge_text: list[str] = []
        if robust_edge is not None:
            edge_text.append(f"robust edge {_percent(robust_edge, signed=True)}")
        if stressed_edge is not None:
            edge_text.append(f"stressed edge {_percent(stressed_edge, signed=True)}")
        rationale_parts.append(
            "After evidence shrinkage and adverse-scenario stress, "
            + " and ".join(edge_text)
            + "."
        )
    if bool(actions.get("deferred")):
        rationale_parts.append(
            f"The underlying decision is {selected_action}, while {effective_action} remains "
            "in force temporarily because persistence or cooldown controls are active."
        )
    if not rationale_parts:
        rationale_parts.append(raw_rationale)
    rationale = " ".join(rationale_parts)

    auditability = _mapping(bundle.get("auditability"))
    component_status = _mapping(bundle.get("component_status"))
    evaluation_status = _mapping(component_status.get("decision_evaluation"))
    release = _mapping(bundle.get("release_identity"))

    return {
        "symbol": symbol,
        "selected_action": selected_action,
        "effective_action": effective_action,
        "deferred": bool(actions.get("deferred")),
        "conclusion": conclusion,
        "rationale": rationale,
        "investment_question": (
            f"Does {symbol} deserve capital relative to {alternative}, cash, and the "
            "portfolio's existing opportunities after costs, downside, uncertainty, and constraints?"
        ),
        "market_backdrop": backdrop_text,
        "what_changed": what_changed,
        "portfolio_posture": portfolio_posture or "Portfolio posture not supplied.",
        "metrics": (
            (
                "Expected return",
                _percent(candidate_return),
                "Specialist-reconciled when available",
            ),
            ("Best alternative", _percent(alternative_return), alternative),
            (
                "Expected downside",
                _percent(downside, signed=True),
                "Decision-horizon downside",
            ),
            (
                "Success probability",
                _percent(success_probability),
                "Governed scenario estimate",
            ),
            (
                "Decision confidence",
                _percent(confidence),
                "Evidence/process reliability",
            ),
            ("Current weight", _percent(current_weight), symbol),
            (
                "Exact-lineage target",
                _percent(target_weight),
                "Not a live-money order",
            ),
            (
                "Decision horizon",
                f"{decision.get('decision_horizon_days', 'Not recorded')} days",
                "Evaluation window",
            ),
        ),
        "bull_case": catalysts or supportive_drivers,
        "committee_support": supportive_drivers,
        "bear_case": bear_points,
        "strongest_dissent": opposing_case,
        "assumptions": assumptions,
        "catalysts": catalysts,
        "portfolio_impact": portfolio_impact,
        "funding_source": funding,
        "implementation": _implementation_reason(decision, construction, actions),
        "monitoring": invalidation,
        "audit": {
            "auditability": _title(
                auditability.get("status")
                or _mapping(bundle.get("record_consistency")).get("state")
            ),
            "decision_identifier": _clean(bundle.get("decision_identifier"))
            or "Unavailable",
            "cycle_identifier": _clean(bundle.get("cycle_identifier"))
            or "Unavailable",
            "snapshot_identifier": _clean(bundle.get("snapshot_identifier"))
            or "Unavailable",
            "code_version": _first_text(
                release.get("decision_code_version"),
                release.get("export_runtime_release"),
                fallback="Unavailable",
            ),
            "evaluation_status": _title(evaluation_status.get("status")),
        },
    }


def _render_list(items: Sequence[str], fallback: str) -> str:
    values = tuple(item for item in items if _clean(item))
    if not values:
        return f'<div class="cio-memo-card-body">{escape(fallback)}</div>'
    rows = "".join(f"<li>{escape(item)}</li>" for item in values)
    return f'<ul class="cio-memo-list">{rows}</ul>'


def _card(
    title: str,
    body: str = "",
    items: Sequence[str] = (),
    *,
    wide: bool = False,
) -> str:
    class_name = "cio-memo-card cio-memo-card-wide" if wide else "cio-memo-card"
    content = (
        f'<div class="cio-memo-card-body">{escape(body)}</div>' if body else ""
    )
    if items:
        content += _render_list(
            items,
            "Not separately recorded for this decision.",
        )
    return (
        f'<section class="{class_name}">'
        f'<div class="cio-memo-card-title">{escape(title)}</div>'
        f"{content}</section>"
    )


def render_investment_memo(
    streamlit_module: ModuleType,
    bundle: Mapping[str, Any],
    *,
    market_backdrop: str = "",
    portfolio_posture: str = "",
) -> Mapping[str, Any]:
    """Render the memo and return its normalized model for deterministic tests."""

    memo = build_investment_memo(
        bundle,
        market_backdrop=market_backdrop,
        portfolio_posture=portfolio_posture,
    )
    metrics = "".join(
        '<div class="cio-memo-metric">'
        f'<div class="cio-memo-metric-label">{escape(label)}</div>'
        f'<div class="cio-memo-metric-value">{escape(str(value))}</div>'
        f'<div class="cio-memo-metric-note">{escape(note)}</div></div>'
        for label, value, note in memo["metrics"]
    )
    action_pills = (
        f'<span class="cio-memo-pill">Selected: {escape(memo["selected_action"])}</span>'
        f'<span class="cio-memo-pill">Effective now: {escape(memo["effective_action"])}</span>'
        f'<span class="cio-memo-pill">{escape(memo["portfolio_posture"])}</span>'
    )
    audit = memo["audit"]
    audit_text = (
        f'Auditability: {escape(audit["auditability"])} · '
        f'Evaluation: {escape(audit["evaluation_status"])}<br>'
        f'Decision: {escape(audit["decision_identifier"])}<br>'
        f'Cycle: {escape(audit["cycle_identifier"])}<br>'
        f'Snapshot: {escape(audit["snapshot_identifier"])}<br>'
        f'Code version: {escape(audit["code_version"])}'
    )
    markup = (
        _CSS
        + '<div class="cio-memo-shell">'
        + '<section class="cio-memo-hero">'
        + '<div class="cio-memo-kicker">CIO investment memo</div>'
        + f'<div class="cio-memo-title">{escape(memo["symbol"])} · '
        + f'{escape(memo["effective_action"])}</div>'
        + f'<div class="cio-memo-summary">{escape(memo["conclusion"])}</div>'
        + f'<div class="cio-memo-action-row">{action_pills}</div>'
        + "</section>"
        + f'<div class="cio-memo-metrics">{metrics}</div>'
        + '<div class="cio-memo-grid">'
        + _card("The investment question", memo["investment_question"], wide=True)
        + _card("Market backdrop", memo["market_backdrop"])
        + _card("What changed", memo["what_changed"])
        + _card(
            "Why the CIO reached this conclusion",
            memo["rationale"],
            wide=True,
        )
        + _card("Bull case", items=memo["bull_case"])
        + _card(
            "Bear case",
            memo["strongest_dissent"],
            memo["bear_case"],
        )
        + _card("Key assumptions", items=memo["assumptions"])
        + _card("Catalysts", items=memo["catalysts"])
        + _card(
            "Portfolio impact",
            memo["portfolio_impact"] + " " + memo["funding_source"],
        )
        + _card("Implementation", memo["implementation"])
        + _card(
            "What would change the decision",
            items=memo["monitoring"],
            wide=True,
        )
        + "</div>"
        + f'<div class="cio-memo-audit">{audit_text}</div>'
        + "</div>"
    )
    streamlit_module.markdown(markup, unsafe_allow_html=True)
    return memo


__all__ = ["build_investment_memo", "render_investment_memo"]
