from __future__ import annotations

from copy import deepcopy

from cio_report_governance_refinement import refine_report_bundle


DECISION_AS_OF = "2026-08-09T15:19:00.014206+00:00"
REVIEW_AT = "2026-09-08T15:19:00.014206+00:00"
CANDIDATE_ID = "candidate:paper-pilot:test:LTCUSD"


def _bundle() -> dict:
    return {
        "decision_as_of": DECISION_AS_OF,
        "auditability": {
            "status": "auditable",
            "issues": [],
            "decision_scope": "cycle_level_no_action",
            "cycle_disposition_is_canonical_cio_authority": True,
        },
        "record_consistency": {"state": "non_auditable"},
        "component_status": {
            "decision_evaluation": {
                "recorded": False,
                "due_at": None,
                "status": "pending_without_resolved_due_date",
            }
        },
        "records": {
            "cio_decision": None,
            "opportunity_queue": {
                "context_identifier": "opportunity:paper-pilot:test",
                "code_version": "abc123",
                "policy_version": "opportunity-qualification.v7-economic-consistency",
            },
            "candidate_decisions_considered": [
                {
                    "identifier": CANDIDATE_ID,
                    "review_at": REVIEW_AT,
                    "model_versions": [
                        "direct-global-market-evidence.v1",
                        "market-expectations-gap.v1-pilot-proxy",
                    ],
                    "payoff_distribution": [],
                    "scenarios": {
                        "base": {"probability": 0.55, "return": 0.04},
                        "bear": {"probability": 0.25, "return": -0.30},
                        "bull": {"probability": 0.20, "return": 0.28},
                    },
                    "instrument": {
                        "security_master_snapshot_identifier": "direct-market-universe:test",
                        "security_master_record_identifiers": [
                            "direct-market-instrument:LTCUSD"
                        ],
                    },
                }
            ],
        },
        "investment_analysis": {
            "opportunity_funnel": {
                "scope": "opportunity_qualification",
                "candidate_records_considered": 1,
                "qualified_for_specialist_synthesis": 0,
                "rejected_before_specialist_synthesis": 1,
                "specialist_packets_recorded": 0,
                "cio_candidate_decisions_recorded": 0,
            },
            "portfolio_relative_opportunity": {
                "candidate_identifier": CANDIDATE_ID,
                "payoff_distribution": [],
            },
            "top_rejected_opportunities": [
                {"candidate_identifier": CANDIDATE_ID, "payoff_distribution": []}
            ],
        },
    }


def test_reconciles_cycle_auditability_without_fake_candidate_cio_decision() -> None:
    result = refine_report_bundle(_bundle())

    assert result["auditability"]["status"] == "auditable"
    assert result["record_consistency"]["state"] == "aligned"
    assert result["record_consistency"]["auditability_source"] == "canonical_cycle_auditability"
    funnel = result["investment_analysis"]["opportunity_funnel"]
    assert funnel["opportunity_qualification_candidates_considered"] == 1
    assert funnel["candidate_level_cio_decisions_recorded"] == 0
    assert funnel["cio_candidate_decisions_recorded"] == 0
    assert funnel["reconciliation"]["status"] == "balanced"


def test_funnel_mismatch_makes_report_non_auditable() -> None:
    bundle = _bundle()
    bundle["investment_analysis"]["opportunity_funnel"]["candidate_records_considered"] = 2

    result = refine_report_bundle(bundle)

    assert result["auditability"]["status"] == "non_auditable"
    assert "opportunity_funnel:candidate_count_mismatch" in result["auditability"]["issues"]
    assert result["record_consistency"]["state"] == "non_auditable"


def test_no_action_evaluation_uses_earliest_candidate_review_date() -> None:
    result = refine_report_bundle(_bundle())
    evaluation = result["component_status"]["decision_evaluation"]

    assert evaluation["status"] == "pending_cycle_review"
    assert evaluation["due_at"] == REVIEW_AT
    assert evaluation["due_at_source"] == "earliest_considered_candidate_review_at"
    assert evaluation["evaluation_scope"] == "cycle_level_no_action"


def test_no_action_evaluation_has_policy_fallback_when_no_candidate_review_exists() -> None:
    bundle = _bundle()
    bundle["records"]["candidate_decisions_considered"] = []

    result = refine_report_bundle(bundle)
    evaluation = result["component_status"]["decision_evaluation"]

    assert evaluation["status"] == "pending_cycle_review"
    assert evaluation["due_at"] == "2026-09-08T15:19:00.014206+00:00"
    assert evaluation["due_at_source"] == "cycle_no_action_policy_default_30_days"


def test_payoff_and_probability_provenance_are_explicit() -> None:
    result = refine_report_bundle(_bundle())
    opportunity = result["investment_analysis"]["portfolio_relative_opportunity"]

    assert opportunity["payoff_distribution"] == []
    assert opportunity["payoff_distribution_status"] == "canonical_three_scenario_fallback"
    provenance = opportunity["scenario_probability_provenance"]
    assert provenance["source"] == "candidate_decision_record"
    assert provenance["probabilities_sum_to_one"] is True
    assert provenance["calibration_metadata_status"] == "not_recorded"


def test_upstream_lineage_reports_only_persisted_evidence() -> None:
    result = refine_report_bundle(_bundle())
    lineage = result["investment_analysis"]["upstream_lineage"]

    assert lineage["opportunity_context_identifier"] == "opportunity:paper-pilot:test"
    assert lineage["security_master_snapshot_identifiers"] == ["direct-market-universe:test"]
    assert lineage["security_master_record_identifiers"] == ["direct-market-instrument:LTCUSD"]
    assert lineage["discovery_diagnostic_identifier"] is None
    assert lineage["discovery_diagnostic_status"] == "not_linked_in_opportunity_report"


def test_refinement_preserves_authoritative_inputs_and_thresholds() -> None:
    bundle = _bundle()
    bundle["decision_actions"] = {
        "selected_action": "no_superior_opportunity",
        "effective_action": "no_superior_opportunity",
    }
    bundle["authority"] = {"paper_only": True, "real_money_authorized": False}
    original = deepcopy(bundle)

    result = refine_report_bundle(bundle)

    assert bundle == original
    assert result["decision_actions"] == original["decision_actions"]
    assert result["authority"] == original["authority"]
    semantics = result["investment_analysis"]["qualification_semantics"]
    assert semantics["minimum_research_viability_is_not_full_conviction"] is True
    assert semantics["numeric_thresholds_changed_by_reporting_refinement"] is False
