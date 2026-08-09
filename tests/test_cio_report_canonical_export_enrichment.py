from __future__ import annotations

from types import ModuleType, SimpleNamespace

from cio_decision_export import build_cio_decision_export
import cio_report_canonical_export_enrichment as canonical_export


def test_canonical_full_report_export_enriches_cycle_level_no_action(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "release-cycle-aware")
    as_of = "2026-08-09T13:00:42.193112+00:00"
    cycle_identifier = "canonical-cycle:current"
    decision_identifier = "cio-cycle-disposition:current"
    briefing = {
        "identifier": "daily-cio:current",
        "decision_identifier": decision_identifier,
        "cycle_identifier": cycle_identifier,
        "as_of": as_of,
        "code_version": "release-cycle-aware",
        "portfolio_decision": "CIO decision: no superior opportunity.",
        "evidence_that_changes_conclusion": [
            "expected return must clear the full-conviction threshold"
        ],
        "cycle_disposition": {
            "identifier": decision_identifier,
            "action": "no_superior_opportunity",
            "authority": "CHIEF_INVESTMENT_OFFICER",
            "classification": "economically_unqualified",
            "as_of": as_of,
            "rationale": "No candidate clears the governed economic hurdles.",
        },
    }
    queue = {
        "identifier": "opportunity-queue:current",
        "as_of": as_of,
        "ranked": [],
        "rejected": [
            {
                "candidate_identifier": "candidate:abc",
                "analysis_lane": "us_equity",
                "effective_opportunity_cost": 0.08,
                "opportunity_edge": 0.015,
                "best_alternative_identifier": "cash",
                "best_alternative_kind": "cash",
                "reasons": ["expected return below full-conviction threshold"],
            }
        ],
    }
    candidate = {
        "identifier": "candidate:abc",
        "instrument": {"symbol": "ABC", "asset_class": "us_equity"},
        "net_expected_return": 0.095,
        "expected_downside": -0.12,
        "probability_of_success": 0.58,
        "liquidity_score": 0.91,
        "implementation_cost_return": 0.001,
        "evidence_quality": {"score": 0.87},
        "decision_horizon_days": 365,
        "scenarios": {"base": 0.10, "bear": -0.12, "bull": 0.24},
    }
    histories = {
        "opportunity_queue": [queue],
        "candidate_decision": [candidate],
        "specialist_packet": [],
    }
    app = SimpleNamespace(
        _history=lambda event_type, limit=2000: histories.get(event_type, [])[:limit],
        _latest=lambda event_type: (histories.get(event_type) or [None])[0],
    )
    session_navigation = ModuleType("fake_session_navigation")

    def decision_bundle(app: object, *, briefing: object, construction: object):
        del app, construction
        return build_cio_decision_export(
            cio_decision=None,
            daily_cio_briefing=briefing,
            decision_evidence_snapshot=None,
            portfolio_construction=None,
            decision_evaluation=None,
        )

    session_navigation._decision_bundle = decision_bundle
    canonical_export.install(session_navigation)

    exported = session_navigation._decision_bundle(
        app,
        briefing=briefing,
        construction=None,
    )

    assert exported["auditability"]["status"] == "auditable"
    assert exported["auditability"]["issues"] == []
    assert exported["auditability"]["decision_scope"] == "cycle_level_no_action"
    assert exported["release_identity"]["decision_code_version"] == "release-cycle-aware"
    assert exported["release_identity"]["decision_release_recorded"] is True
    assert exported["decision_actions"]["selected_action"] == "no_superior_opportunity"
    assert exported["records"]["cio_decision"] is None
    assert exported["records"]["decision_evidence_snapshot"] is None
    assert exported["records"]["opportunity_queue"]["identifier"] == "opportunity-queue:current"
    analysis = exported["investment_analysis"]
    assert analysis["opportunity_funnel"]["candidate_records_considered"] == 1
    assert analysis["opportunity_funnel"]["qualified_for_specialist_synthesis"] == 0
    assert analysis["specialist_review"]["status"] == "not_applicable_no_candidate_qualified"
    strongest = analysis["top_rejected_opportunities"][0]
    assert strongest["symbol"] == "ABC"
    assert strongest["net_expected_return"] == 0.095
    assert strongest["effective_opportunity_cost"] == 0.08
    assert strongest["opportunity_edge"] == 0.015
    assert exported["authority"]["read_only_export"] is True
    assert exported["authority"]["paper_only"] is True
    assert exported["authority"]["real_money_authorized"] is False
