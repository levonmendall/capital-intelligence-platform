"""Tighten cycle-level CIO report governance without changing investment authority.

This module is deliberately report-only.  It reconciles audit state, makes the
opportunity-qualification funnel explicit, records upstream lineage that is
actually present, explains scenario/payoff provenance, and schedules evaluation
of canonical cycle-level no-action decisions.  It does not change evidence,
qualification thresholds, ranking, specialist conclusions, CIO authority,
construction, sizing, execution, or live-money capability.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Mapping, MutableMapping, Sequence


DEFAULT_NO_ACTION_EVALUATION_DAYS = 30
_CYCLE_NO_ACTION_SCOPE = "cycle_level_no_action"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _parse_time(value: object) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _candidate_map(records: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for candidate in _sequence(records.get("candidate_decisions_considered")):
        if not isinstance(candidate, Mapping):
            continue
        identifier = _clean(candidate.get("identifier"))
        if identifier:
            result[identifier] = candidate
    return result


def _candidate_scenario_metadata(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        return {
            "payoff_distribution_status": "candidate_record_unavailable",
            "scenario_probability_provenance": {
                "source": "candidate_record_unavailable",
                "probabilities_sum_to_one": None,
                "calibration_metadata_status": "not_recorded",
            },
        }

    payoff = _sequence(candidate.get("payoff_distribution"))
    scenarios = _mapping(candidate.get("scenarios"))
    probabilities: list[float] = []
    for name in ("base", "bear", "bull"):
        row = scenarios.get(name)
        if not isinstance(row, Mapping):
            continue
        value = row.get("probability")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            probabilities.append(float(value))

    probability_total = sum(probabilities) if probabilities else None
    probability_check = (
        abs(probability_total - 1.0) <= 1e-6 if probability_total is not None else None
    )
    model_versions = [
        _clean(value)
        for value in _sequence(candidate.get("model_versions"))
        if _clean(value)
    ]
    return {
        "payoff_distribution_status": (
            "explicit_distribution" if payoff else "canonical_three_scenario_fallback"
        ),
        "scenario_probability_provenance": {
            "source": "candidate_decision_record",
            "model_versions": model_versions,
            "probabilities_sum_to_one": probability_check,
            "probability_total": probability_total,
            "calibration_metadata_status": (
                "recorded"
                if candidate.get("scenario_calibration") is not None
                else "not_recorded"
            ),
        },
    }


def _enrich_candidate_analysis(
    analysis: MutableMapping[str, Any],
    candidates: Mapping[str, Mapping[str, Any]],
) -> None:
    identifier = _clean(analysis.get("candidate_identifier"))
    metadata = _candidate_scenario_metadata(candidates.get(identifier))
    analysis.update(metadata)


def _upstream_lineage(
    records: Mapping[str, Any],
    candidates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    queue = _mapping(records.get("opportunity_queue"))
    security_master_snapshots: set[str] = set()
    security_master_records: set[str] = set()
    for candidate in candidates.values():
        instrument = _mapping(candidate.get("instrument"))
        snapshot = _clean(instrument.get("security_master_snapshot_identifier"))
        if snapshot:
            security_master_snapshots.add(snapshot)
        for identifier in _sequence(instrument.get("security_master_record_identifiers")):
            cleaned = _clean(identifier)
            if cleaned:
                security_master_records.add(cleaned)

    return {
        "opportunity_context_identifier": _clean(queue.get("context_identifier")) or None,
        "opportunity_queue_code_version": _clean(queue.get("code_version")) or None,
        "opportunity_policy_version": _clean(queue.get("policy_version")) or None,
        "security_master_snapshot_identifiers": sorted(security_master_snapshots),
        "security_master_record_identifiers": sorted(security_master_records),
        "discovery_diagnostic_identifier": None,
        "discovery_diagnostic_status": "not_linked_in_opportunity_report",
        "comprehensive_discovery_counts_status": "not_available_in_cycle_report",
        "note": (
            "Only persisted lineage is reported here. Comprehensive discovery/catalog "
            "counts must remain separately certified and are never inferred from the "
            "opportunity queue."
        ),
    }


def _evaluation_due_at(report: Mapping[str, Any], records: Mapping[str, Any]) -> tuple[str | None, str]:
    decision_as_of = _parse_time(report.get("decision_as_of"))
    candidate_dates: list[datetime] = []
    for candidate in _sequence(records.get("candidate_decisions_considered")):
        if not isinstance(candidate, Mapping):
            continue
        review_at = _parse_time(candidate.get("review_at"))
        if review_at is not None and (decision_as_of is None or review_at >= decision_as_of):
            candidate_dates.append(review_at)
    if candidate_dates:
        return min(candidate_dates).isoformat(), "earliest_considered_candidate_review_at"
    if decision_as_of is not None:
        return (
            decision_as_of + timedelta(days=DEFAULT_NO_ACTION_EVALUATION_DAYS)
        ).isoformat(), "cycle_no_action_policy_default_30_days"
    return None, "unresolved_missing_decision_time"


def _mark_audit_issue(report: MutableMapping[str, Any], issue: str) -> None:
    auditability = _mapping(report.get("auditability"))
    issues = [_clean(value) for value in _sequence(auditability.get("issues")) if _clean(value)]
    if issue not in issues:
        issues.append(issue)
    auditability["issues"] = issues
    auditability["status"] = "non_auditable"
    report["auditability"] = auditability


def refine_report_bundle(bundle: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a governance-consistent copy of an already enriched CIO report."""

    report: dict[str, Any] = deepcopy(dict(bundle))
    records = _mapping(report.get("records"))
    analysis = _mapping(report.get("investment_analysis"))
    funnel = _mapping(analysis.get("opportunity_funnel"))
    candidates = _candidate_map(records)

    considered = funnel.get("candidate_records_considered")
    qualified = funnel.get("qualified_for_specialist_synthesis")
    rejected = funnel.get("rejected_before_specialist_synthesis")
    specialist_packets = funnel.get("specialist_packets_recorded")

    if isinstance(considered, int):
        funnel["opportunity_qualification_candidates_considered"] = considered
    candidate_level_cio_count = 1 if isinstance(records.get("cio_decision"), Mapping) else 0
    funnel["candidate_level_cio_decisions_recorded"] = candidate_level_cio_count
    # Keep the legacy field for compatibility, but make its meaning truthful.
    funnel["cio_candidate_decisions_recorded"] = candidate_level_cio_count

    count_balanced = (
        isinstance(considered, int)
        and isinstance(qualified, int)
        and isinstance(rejected, int)
        and considered == qualified + rejected
    )
    specialist_balanced = (
        isinstance(qualified, int)
        and isinstance(specialist_packets, int)
        and specialist_packets == qualified
    )
    funnel["reconciliation"] = {
        "candidate_count_balanced": count_balanced,
        "specialist_packet_count_balanced": specialist_balanced,
        "candidate_equation": (
            "opportunity_qualification_candidates_considered = "
            "qualified_for_specialist_synthesis + rejected_before_specialist_synthesis"
        ),
        "specialist_equation": (
            "specialist_packets_recorded = qualified_for_specialist_synthesis"
        ),
        "status": "balanced" if count_balanced and specialist_balanced else "mismatch",
    }
    analysis["opportunity_funnel"] = funnel

    relative = analysis.get("portfolio_relative_opportunity")
    if isinstance(relative, MutableMapping):
        _enrich_candidate_analysis(relative, candidates)
    rejected_rows = analysis.get("top_rejected_opportunities")
    if isinstance(rejected_rows, list):
        for row in rejected_rows:
            if isinstance(row, MutableMapping):
                _enrich_candidate_analysis(row, candidates)

    analysis["upstream_lineage"] = _upstream_lineage(records, candidates)
    analysis["qualification_semantics"] = {
        "minimum_research_viability_is_not_full_conviction": True,
        "canonical_allocation_gate": "all_governed_economic_and_robustness_controls",
        "sub_canonical_advancement": (
            "A candidate may advance only to a non-authoritative participation or "
            "exploration lane when the qualification policy's viability conditions pass."
        ),
        "capital_authority": (
            "Research-lane advancement does not authorize positive canonical capital."
        ),
        "numeric_thresholds_changed_by_reporting_refinement": False,
    }
    report["investment_analysis"] = analysis

    decision_scope = _clean(report.get("auditability", {}).get("decision_scope")) if isinstance(report.get("auditability"), Mapping) else ""
    if decision_scope == _CYCLE_NO_ACTION_SCOPE:
        evaluation = _mapping(report.get("component_status", {}).get("decision_evaluation")) if isinstance(report.get("component_status"), Mapping) else {}
        if not evaluation.get("recorded") and not _clean(evaluation.get("due_at")):
            due_at, source = _evaluation_due_at(report, records)
            evaluation.update(
                {
                    "due_at": due_at,
                    "due_at_source": source,
                    "evaluation_scope": _CYCLE_NO_ACTION_SCOPE,
                    "status": "pending_cycle_review" if due_at else "pending_without_resolved_due_date",
                }
            )
            component_status = _mapping(report.get("component_status"))
            component_status["decision_evaluation"] = evaluation
            report["component_status"] = component_status

    if not count_balanced:
        _mark_audit_issue(report, "opportunity_funnel:candidate_count_mismatch")
    if not specialist_balanced:
        _mark_audit_issue(report, "opportunity_funnel:specialist_packet_count_mismatch")

    # There is one canonical auditability result.  Generic record consistency must
    # not independently downgrade a valid cycle-level no-action disposition merely
    # because no synthetic candidate-level CIO record exists.
    auditability = _mapping(report.get("auditability"))
    record_consistency = _mapping(report.get("record_consistency"))
    record_consistency["state"] = (
        "aligned" if auditability.get("status") == "auditable" else "non_auditable"
    )
    record_consistency["auditability_source"] = "canonical_cycle_auditability"
    report["record_consistency"] = record_consistency

    report["report_governance_version"] = "cio-report-governance.v1"
    return report


__all__ = ["DEFAULT_NO_ACTION_EVALUATION_DAYS", "refine_report_bundle"]
