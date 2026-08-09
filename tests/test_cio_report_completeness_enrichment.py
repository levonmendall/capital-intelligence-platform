from __future__ import annotations

from types import SimpleNamespace

from cio_report_completeness_enrichment import enrich_report_bundle


AS_OF = "2026-08-09T05:15:09.277579+00:00"
DECISION_ID = (
    "cio-cycle-disposition:opportunity:paper-pilot:20260809T051509277579Z:"
    + AS_OF
)
CYCLE_ID = "canonical-cycle:screening:paper-pilot:20260809T051509277579Z"
RELEASE = "2dc27de7585cd4fe86234c00e4037c5627578696"


def _briefing():
    return {
        "as_of": AS_OF,
        "decision_identifier": DECISION_ID,
        "cycle_identifier": CYCLE_ID,
        "code_version": RELEASE,
        "portfolio_decision": "CIO decision: no superior opportunity. No portfolio action is required.",
        "evidence_that_changes_conclusion": [
            "horizon-normalized evidence-adjusted expected return is below the full-conviction threshold",
            "horizon-normalized opportunity edge is below the full-conviction margin",
        ],
        "cycle_disposition": {
            "identifier": DECISION_ID,
            "as_of": AS_OF,
            "action": "no_superior_opportunity",
            "classification": "economically_unqualified",
            "rationale": "No candidate clears the governed economic hurdles.",
            "primary_reason": "horizon-normalized evidence-adjusted expected return is below the full-conviction threshold",
            "contributing_reasons": [
                "horizon-normalized evidence-adjusted expected return is below the full-conviction threshold",
                "horizon-normalized opportunity edge is below the full-conviction margin",
            ],
            "reason_categories": ["economic_return", "economic_return"],
            "authority": "CHIEF_INVESTMENT_OFFICER",
            "policy_version": "cio-empty-queue-disposition.v2",
        },
    }


def _queue():
    return {
        "occurred_at": AS_OF,
        "context_identifier": "opportunity:paper-pilot:20260809T051509277579Z",
        "policy_version": "opportunity-policy.v1",
        "has_qualified_opportunity": False,
        "ranked": [],
        "rejected": [
            {
                "candidate_identifier": "candidate:BTCUSD",
                "outcome": "rejected",
                "analysis_lane": "crypto",
                "effective_opportunity_cost": 0.09,
                "opportunity_edge": 0.01,
                "best_alternative_identifier": "holding:MCD",
                "best_alternative_kind": "current_holding",
                "resolved_policy_profile": {"minimum_opportunity_edge": 0.02},
                "reasons": [
                    "horizon-normalized opportunity edge is below the full-conviction margin"
                ],
            },
            {
                "candidate_identifier": "candidate:ETHUSD",
                "outcome": "rejected",
                "analysis_lane": "crypto",
                "effective_opportunity_cost": 0.09,
                "opportunity_edge": -0.01,
                "best_alternative_identifier": "holding:MCD",
                "best_alternative_kind": "current_holding",
                "resolved_policy_profile": {"minimum_opportunity_edge": 0.02},
                "reasons": [
                    "horizon-normalized expected return does not clearly exceed the best capital alternative"
                ],
            },
        ],
    }


def _candidate(identifier: str, symbol: str, expected: float):
    return {
        "identifier": identifier,
        "as_of": AS_OF,
        "instrument": {
            "symbol": symbol,
            "asset_class": "crypto",
        },
        "net_expected_return": expected,
        "expected_downside": -0.18,
        "probability_of_success": 0.58,
        "liquidity_score": 0.92,
        "implementation_cost_return": 0.002,
        "decision_horizon_days": 365,
        "evidence_quality": {"score": 0.91},
        "scenarios": {
            "bear": {"return": -0.30, "probability": 0.25},
            "base": {"return": 0.10, "probability": 0.50},
            "bull": {"return": 0.35, "probability": 0.25},
        },
    }


def _app():
    histories = {
        "opportunity_queue": (_queue(),),
        "candidate_decision": (
            _candidate("candidate:BTCUSD", "BTCUSD", 0.10),
            _candidate("candidate:ETHUSD", "ETHUSD", 0.08),
        ),
        "specialist_packet": (),
    }

    def history(event_type, *, limit=2000):
        del limit
        return histories.get(event_type, ())

    def latest(event_type):
        values = histories.get(event_type, ())
        return values[0] if values else None

    return SimpleNamespace(_history=history, _latest=latest)


def _bundle():
    briefing = _briefing()
    return {
        "schema_version": "cio-decision-export.v3",
        "decision_identifier": DECISION_ID,
        "cycle_identifier": CYCLE_ID,
        "auditability": {
            "status": "non_auditable",
            "issues": [
                "cio_decision:missing_for_decision",
                "decision_evidence_snapshot:missing_for_decision",
                "cio_decision:code_version_not_recorded",
            ],
        },
        "release_identity": {
            "decision_code_version": None,
            "decision_release_recorded": False,
            "export_runtime_release": RELEASE,
        },
        "decision_actions": {
            "selected_action": None,
            "effective_action": None,
            "deferred": False,
            "hysteresis_applied": False,
        },
        "record_presence": {
            "cio_decision": False,
            "daily_cio_briefing": True,
            "decision_evidence_snapshot": False,
        },
        "records": {
            "cio_decision": None,
            "daily_cio_briefing": briefing,
            "decision_evidence_snapshot": None,
            "portfolio_construction": None,
            "decision_evaluation": None,
        },
        "reader_summary": {"status": "incomplete"},
        "authority": {
            "read_only_export": True,
            "candidate_authority": False,
            "ranking_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        },
    }


def test_empty_queue_cycle_disposition_is_auditable_without_fabricated_candidate_decision():
    report = enrich_report_bundle(_app(), _bundle())

    assert report["auditability"]["status"] == "auditable"
    assert report["auditability"]["decision_scope"] == "cycle_level_no_action"
    assert report["auditability"]["cycle_disposition_is_canonical_cio_authority"] is True
    assert report["release_identity"]["decision_code_version"] == RELEASE
    assert report["release_identity"]["decision_release_recorded"] is True
    assert report["records"]["cio_decision"] is None
    assert report["records"]["cycle_disposition"]["identifier"] == DECISION_ID
    assert report["records"]["opportunity_queue"]["occurred_at"] == AS_OF


def test_report_exposes_quantitative_rejected_opportunities_and_funnel():
    report = enrich_report_bundle(_app(), _bundle())
    analysis = report["investment_analysis"]
    funnel = analysis["opportunity_funnel"]

    assert funnel["candidate_records_considered"] == 2
    assert funnel["qualified_for_specialist_synthesis"] == 0
    assert funnel["rejected_before_specialist_synthesis"] == 2
    assert funnel["market_lane_qualification_counts"] == {"crypto": 2}
    assert analysis["specialist_review"]["status"] == (
        "not_applicable_no_candidate_qualified"
    )

    strongest = analysis["top_rejected_opportunities"][0]
    assert strongest["symbol"] == "BTCUSD"
    assert strongest["net_expected_return"] == 0.10
    assert strongest["effective_opportunity_cost"] == 0.09
    assert strongest["opportunity_edge"] == 0.01
    assert strongest["expected_downside"] == -0.18
    assert strongest["probability_of_success"] == 0.58
    assert strongest["best_alternative_identifier"] == "holding:MCD"
    assert strongest["scenarios"]["bear"]["return"] == -0.30


def test_cycle_report_preserves_read_only_paper_governance():
    report = enrich_report_bundle(_app(), _bundle())

    assert report["decision_actions"]["effective_action"] == "no_superior_opportunity"
    assert report["reader_summary"]["status"] == "complete"
    assert report["reader_summary"]["headline"] == (
        "No portfolio change — no superior opportunity"
    )
    assert report["authority"]["paper_only"] is True
    assert report["authority"]["real_money_authorized"] is False
    assert report["authority"]["execution_authority"] is False
