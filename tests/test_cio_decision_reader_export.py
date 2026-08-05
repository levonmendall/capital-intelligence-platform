from __future__ import annotations

import json
from types import SimpleNamespace

import cio_decision_reader_export as reader


DECISION_ID = "cio-decision:candidate:mcd:2026-08-05"
CYCLE_ID = "canonical-cycle:2026-08-05"


def _briefing() -> dict[str, object]:
    return {
        "decision_identifier": DECISION_ID,
        "cycle_identifier": CYCLE_ID,
        "candidate_identifier": "candidate:mcd:2026-08-05",
        "confidence": 0.54102907,
        "material_developments": (
            "Company quality, growth, valuation, momentum, and regime evidence changed the expected-return estimate",
            "Cost-adjusted expected return is 38.42%",
            "Opportunity edge is 1.42%",
            "CIO action is no material change",
        ),
        "opportunity_or_risk": (
            "MCD is ranked #1; the central risk is quality evidence could "
            "deteriorate after the decision time"
        ),
        "portfolio_decision": (
            "CIO decision: no material change. "
            "No executable portfolio change is proposed."
        ),
        "what_changed": (
            "Company quality, growth, valuation, momentum, and regime evidence "
            "changed the expected-return estimate"
        ),
        "why_it_matters": (
            "The candidate offers a 38.42% cost-adjusted expected return versus "
            "a 37.00% alternative, with 17.26% expected downside."
        ),
        "evidence_that_changes_conclusion": (
            "Expected return falls below the opportunity qualification threshold",
            "Evidence quality or freshness falls below policy",
            "A qualified replacement offers a materially superior opportunity edge",
        ),
    }


def _aligned_bundle() -> dict[str, object]:
    return {
        "schema_version": "cio-decision-export.v2",
        "decision_identifier": DECISION_ID,
        "cycle_identifier": CYCLE_ID,
        "decision_actions": {
            "selected_action": "hold",
            "effective_action": "hold",
            "deferred": False,
            "hysteresis_applied": False,
        },
        "auditability": {"status": "auditable", "issues": []},
        "records": {
            "daily_cio_briefing": _briefing(),
            "cio_decision": {
                "identifier": DECISION_ID,
                "candidate_identifier": "candidate:mcd:2026-08-05",
                "action": "hold",
                "expected_return": 0.38419514,
                "effective_opportunity_cost": 0.3699756,
                "probability_of_success": 0.75216099,
                "final_confidence": 0.54102907,
                "risks": (
                    "analytical coverage is incomplete",
                    "Realized annualized volatility=59.80%",
                ),
                "invalidation_conditions": (
                    "Expected return falls below the opportunity qualification threshold",
                    "Evidence quality or freshness falls below policy",
                ),
            },
            "decision_evidence_snapshot": {
                "decision_identifier": DECISION_ID,
                "symbol": "MCD",
                "expected_return": 0.38419514,
                "effective_opportunity_cost": 0.3699756,
                "expected_downside": -0.1726,
                "probability_of_success": 0.75216099,
                "opportunity_rank": 1,
            },
            "portfolio_construction": None,
            "decision_evaluation": None,
        },
    }


def test_reader_summary_is_plain_language_and_first_in_json() -> None:
    enriched = reader.enrich_cio_decision_export(
        _aligned_bundle(),
        current_market_context=(
            "The U.S. session is open. Inflation is easing while rates remain "
            "restrictive."
        ),
    )
    summary = enriched["reader_summary"]

    assert summary["status"] == "complete"
    assert summary["headline"] == "No portfolio change"
    assert "kept the portfolio unchanged" in summary["summary"]
    assert "38.4% return after costs" in summary["summary"]
    assert "1.4 percentage points" in summary["summary"]
    assert "17.3%" in summary["summary"]
    assert "75.2%" in summary["summary"]
    assert any(item.startswith("MCD ranked #1") for item in summary["why"])
    assert "cost-adjusted expected return" not in summary["summary"]
    assert "opportunity edge" not in summary["summary"]
    assert summary["current_market_context"]["scope"] == "current_at_export_time"

    encoded = reader.cio_decision_reader_json(enriched)
    decoded = json.loads(encoded)
    assert list(decoded)[:2] == ["reader_summary", "schema_version"]


def test_briefing_only_summary_is_useful_but_explicitly_unverified() -> None:
    bundle = _aligned_bundle()
    bundle["auditability"] = {
        "status": "non_auditable",
        "issues": [
            "cio_decision:missing_for_decision",
            "decision_evidence_snapshot:missing_for_decision",
            "portfolio_construction:lineage_unproven",
        ],
    }
    records = dict(bundle["records"])
    records["cio_decision"] = None
    records["decision_evidence_snapshot"] = None
    bundle["records"] = records
    bundle["decision_actions"] = {
        "selected_action": None,
        "effective_action": None,
        "deferred": False,
        "hysteresis_applied": False,
    }

    summary = reader.build_reader_summary(bundle)

    assert summary["status"] == "incomplete"
    assert summary["headline"] == "Briefing reports the current portfolio action"
    assert "briefing-only explanation" in summary["portfolio_action"]
    assert "38.4% return after costs" in summary["summary"]
    assert "17.3%" in summary["summary"]
    assert "matching detailed CIO decision record is missing" in summary["audit_note"]
    assert summary["key_numbers"]["opportunity_rank"] == 1


def test_selector_uses_matching_mcd_records_not_latest_klac_records() -> None:
    histories = {
        "cio_decision": (
            {"identifier": "decision:klac", "action": "hold"},
            {"identifier": DECISION_ID, "action": "hold"},
        ),
        "decision_evidence_snapshot": (
            {"decision_identifier": "decision:klac", "symbol": "KLAC"},
            {"decision_identifier": DECISION_ID, "symbol": "MCD"},
        ),
        "portfolio_construction": (
            {"cycle_identifier": "cycle:older", "trades": [{"symbol": "KLAC"}]},
            {"cycle_identifier": CYCLE_ID, "trades": []},
        ),
        "decision_evaluation": (),
    }
    app = SimpleNamespace(
        _history=lambda event_type, *, limit: histories[event_type],
        _latest=lambda event_type: histories[event_type][0]
        if histories[event_type]
        else None,
    )

    selected = reader.select_report_records(
        app,
        daily_cio_briefing=_briefing(),
        portfolio_construction=histories["portfolio_construction"][0],
    )

    assert selected["cio_decision"]["identifier"] == DECISION_ID
    assert selected["decision_evidence_snapshot"]["symbol"] == "MCD"
    assert selected["portfolio_construction"]["cycle_identifier"] == CYCLE_ID
    assert selected["decision_evaluation"] is None
