"""Audit-only trace of evidence through specialists, committee, and CIO.

The trace consumes already-completed canonical records. It cannot alter a
specialist analysis, synthesize an action, size a position, construct a
portfolio, or authorize execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from cio import CIODecision, CandidateDecisionRecord, SpecialistRole
from cio.persistence import CIOJournalEvent, CIOJournalEventType, SQLiteCIOJournal

if TYPE_CHECKING:
    from application.cio_cycle import CandidateCycleContext, CyclePortfolioState
    from application.production_cio import ProductionContextManifest
    from evaluation.point_in_time import DecisionEvidenceSnapshot
    from portfolio.construction_api import PortfolioConstructionResult


_DIRECTIONAL_ROLES = {
    SpecialistRole.MACRO_ECONOMIC.value,
    SpecialistRole.MARKET.value,
    SpecialistRole.CROSS_ASSET_FORECAST.value,
    SpecialistRole.FUNDAMENTAL_VALUATION.value,
}
_DECISION_CONTEXT_PREFIX = "decision-context.v1:"

_ROLE_REQUIREMENTS = {
    SpecialistRole.MACRO_ECONOMIC.value: (
        "point-in-time macro regime",
        "return impact and confidence",
        "tailwinds, headwinds, systemic risks, and scenarios",
        "macro evidence identifiers",
    ),
    SpecialistRole.MARKET.value: (
        "market regime",
        "trend, momentum, breadth, liquidity, and positioning",
        "market evidence, risks, and entry conditions",
    ),
    SpecialistRole.CROSS_ASSET_FORECAST.value: (
        "candidate-specific forecast horizon",
        "calibration, model agreement, stability, and horizon alignment",
        "scenario probabilities, return impacts, and path drawdowns",
        "forecast evidence dependencies",
    ),
    SpecialistRole.FUNDAMENTAL_VALUATION.value: (
        "point-in-time company analysis or asset-specific valuation",
        "valuation and return-driver evidence",
        "contradictory evidence, assumptions, risks, and change conditions",
    ),
    SpecialistRole.PORTFOLIO_RISK.value: (
        "current portfolio and cash",
        "candidate exposure profile and current weight",
        "scenario-aware construction preview",
        "constraints, costs, funding source, and risk budget",
    ),
    SpecialistRole.EVIDENCE_GOVERNANCE.value: (
        "six evidence-quality dimensions",
        "market-data age",
        "evidence identifiers and model versions",
        "point-in-time review boundary and required valuation coverage",
    ),
}

_ROLE_CONTRIBUTION = {
    SpecialistRole.MACRO_ECONOMIC.value: "Macro regime effect and systemic-risk context.",
    SpecialistRole.MARKET.value: "Trend, participation, positioning, and liquidity condition.",
    SpecialistRole.CROSS_ASSET_FORECAST.value: "Calibrated cross-asset distribution and path-risk translation.",
    SpecialistRole.FUNDAMENTAL_VALUATION.value: "Independent valuation, quality, and return-driver challenge.",
    SpecialistRole.PORTFOLIO_RISK.value: "Feasible target ceiling, funding, marginal portfolio effect, and implementation blocks.",
    SpecialistRole.EVIDENCE_GOVERNANCE.value: "Lineage, freshness, completeness, reproducibility, and evidence vetoes.",
}

_CONFIDENCE_METHOD = {
    SpecialistRole.MACRO_ECONOMIC.value: "Governed macro confidence, historical ceiling, and dependency weight.",
    SpecialistRole.MARKET.value: "Governed market confidence, historical ceiling, and dependency weight.",
    SpecialistRole.CROSS_ASSET_FORECAST.value: "Minimum of aggregate confidence, calibration, agreement, stability, and horizon alignment, followed by historical and dependency controls.",
    SpecialistRole.FUNDAMENTAL_VALUATION.value: "Independent valuation confidence followed by historical and dependency controls.",
    SpecialistRole.PORTFOLIO_RISK.value: "Weakest applicable evidence dimension when feasible, followed by historical controls.",
    SpecialistRole.EVIDENCE_GOVERNANCE.value: "Weakest evidence dimension followed by historical controls.",
}

_STALE_MISSING_BEHAVIOR = {
    SpecialistRole.MACRO_ECONOMIC.value: "Production context must exist; upstream evidence governance owns category freshness.",
    SpecialistRole.MARKET.value: "Production context must exist; candidate market-data staleness is enforced by evidence governance.",
    SpecialistRole.CROSS_ASSET_FORECAST.value: "Missing or failed forecast quality causes abstention and zero return impact.",
    SpecialistRole.FUNDAMENTAL_VALUATION.value: "Missing applicable valuation causes abstention and may create an evidence veto.",
    SpecialistRole.PORTFOLIO_RISK.value: "Missing feasible size causes abstention; explicit blocks cause opposition.",
    SpecialistRole.EVIDENCE_GOVERNANCE.value: "Low quality, stale data, missing lineage, or invalid timing produces a categorized veto.",
}


def _tuple_text(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _decision_context(decision: CIODecision) -> Mapping[str, Any] | None:
    for item in decision.monitoring_indicators:
        if not item.startswith(_DECISION_CONTEXT_PREFIX):
            continue
        try:
            decoded = json.loads(item[len(_DECISION_CONTEXT_PREFIX) :])
        except (TypeError, json.JSONDecodeError):
            return None
        return decoded if isinstance(decoded, Mapping) else None
    return None


def _received_inputs(
    role: str,
    *,
    candidate: CandidateDecisionRecord,
    context: "CandidateCycleContext",
    portfolio: "CyclePortfolioState",
) -> tuple[str, ...]:
    if role == SpecialistRole.MACRO_ECONOMIC.value:
        return (
            "macro regime",
            "macro return impact",
            "macro confidence",
            "tailwinds and headwinds",
            "systemic risks and scenarios",
            "macro evidence identifiers",
        )
    if role == SpecialistRole.MARKET.value:
        return (
            "market regime",
            "trend",
            "momentum",
            "breadth",
            "liquidity",
            "positioning",
            "market evidence, risks, and entry conditions",
        )
    if role == SpecialistRole.CROSS_ASSET_FORECAST.value:
        return () if context.forecast is None else (
            "forecast horizon",
            "calibration score",
            "model agreement",
            "forecast stability",
            "scenario probabilities and candidate impacts",
            "path drawdowns",
            "forecast evidence identifiers and dependencies",
        )
    if role == SpecialistRole.FUNDAMENTAL_VALUATION.value:
        if context.company is not None:
            return ("point-in-time company quality, growth, earnings quality, and valuation",)
        if context.asset_valuation is not None:
            return ("point-in-time asset-specific valuation and return drivers",)
        return ()
    if role == SpecialistRole.PORTFOLIO_RISK.value:
        return (
            f"current cash weight={portfolio.cash_weight:.8f}",
            f"current position count={len(portfolio.positions)}",
            "candidate exposure profile",
            "scenario-aware construction preview",
            "constraint evidence, funding source, and review conditions",
        )
    if role == SpecialistRole.EVIDENCE_GOVERNANCE.value:
        return (
            "evidence quality dimensions",
            f"market-data age={candidate.instrument.data_age_hours:.8f} hours",
            "candidate evidence identifiers",
            "candidate model versions",
            "review timestamp",
            "valuation-coverage state",
        )
    return ()


def _missing_inputs(
    role: str,
    *,
    context: "CandidateCycleContext",
) -> tuple[str, ...]:
    if role == SpecialistRole.CROSS_ASSET_FORECAST.value and context.forecast is None:
        return ("governed candidate-specific cross-asset forecast",)
    if (
        role == SpecialistRole.FUNDAMENTAL_VALUATION.value
        and context.company is None
        and context.asset_valuation is None
    ):
        return ("governed company or asset-specific valuation packet",)
    return ()


def _input_status(
    name: str,
    status: str,
    evidence: tuple[str, ...],
) -> dict[str, Any]:
    return {"name": name, "status": status, "evidence": list(evidence)}


def _cio_information_sufficiency(
    *,
    candidate: CandidateDecisionRecord,
    decision: CIODecision,
    packet_payload: Mapping[str, Any],
    portfolio: "CyclePortfolioState",
    decision_context: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    has_valuation = any(
        item.get("role") == SpecialistRole.FUNDAMENTAL_VALUATION.value
        and item.get("position") != "abstain"
        for item in packet_payload.get("analyses", ())
        if isinstance(item, Mapping)
    )
    context_status = "present_structured" if decision_context is not None else "partial"
    benchmark_status = (
        "present_structured_not_authoritative"
        if decision_context is not None
        else "missing"
    )
    return (
        _input_status("expected return and horizon", "present_structured", ("decision.expected_return", "decision.decision_horizon_days")),
        _input_status("return distribution and uncertainty", "present_structured", ("candidate.scenario_distribution", "decision.return_reconciliation")),
        _input_status("downside and tail risk", "present_structured", ("candidate.expected_downside", "reconciled outcomes", "robust and stressed controls")),
        _input_status("cash-relative attractiveness", "present_structured", ("best alternative", "effective opportunity cost", "cash-relative edge")),
        _input_status("benchmark-relative attractiveness", benchmark_status, ("Benchmark comparison is explicitly recorded as unavailable and remains evaluation-only unless an approved point-in-time return is supplied.",)),
        _input_status("valuation", "present_structured" if has_valuation and decision_context is not None else ("present_upstream_only" if has_valuation else "missing"), ("fundamental and valuation specialist record",)),
        _input_status("fundamentals", "present_structured" if has_valuation and decision_context is not None else ("present_upstream_only" if has_valuation else "not_applicable_or_missing"), ("fundamental and valuation specialist record",)),
        _input_status("technical condition", context_status, ("market specialist structured record",)),
        _input_status("catalysts and disconfirming evidence", "present_structured", ("candidate catalysts", "contradictory evidence", "full committee handoff")),
        _input_status("liquidity and costs", "present_structured", ("candidate liquidity", "transaction and slippage costs", "construction constraints")),
        _input_status("data limitations", context_status, ("all specialist limitations are retained in the self-contained context",)),
        _input_status("specialist agreement and disagreement", context_status, ("all role positions, opposition, abstentions, dependency weights, and change conditions",)),
        _input_status("portfolio correlation and diversification effect", "present_structured", ("current positions", "factor loadings", "correlation buckets", "construction result")),
        _input_status("current exposures and available risk budget", "present_structured", (f"positions={len(portfolio.positions)}", f"cash_weight={portfolio.cash_weight:.8f}", "candidate and portfolio ceilings", "funding source")),
        _input_status("proposed risk-adjusted initial target", "present_structured", ("decision.recommended_position_weight", "portfolio feasible ceiling")),
        _input_status("conditions for increasing, reducing, and exiting", context_status, ("structured action ladder", "invalidation conditions", "monitoring indicators")),
    )


@dataclass(frozen=True, slots=True)
class CommitteeCIOInformationTrace:
    payload: Mapping[str, Any]
    schema_version: str = "committee-cio-information-trace.v2-self-contained"

    @property
    def decision_identifier(self) -> str:
        return str(self.payload["decision_identifier"])

    @property
    def as_of(self):
        from datetime import datetime

        return datetime.fromisoformat(str(self.payload["as_of"]))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, **dict(self.payload)}


def build_committee_cio_information_trace(
    *,
    candidate: CandidateDecisionRecord,
    context: "CandidateCycleContext",
    portfolio: "CyclePortfolioState",
    packet_payload: Mapping[str, Any],
    decision: CIODecision,
    snapshot: "DecisionEvidenceSnapshot",
    construction: "PortfolioConstructionResult | None",
    manifest: "ProductionContextManifest | None",
    code_version: str,
) -> CommitteeCIOInformationTrace:
    """Build a complete audit trace from immutable post-decision records."""

    analyses = tuple(
        item for item in packet_payload.get("analyses", ()) if isinstance(item, Mapping)
    )
    origins_by_role = {
        str(item["role"]): set(_tuple_text(item.get("evidence_origin_identifiers")))
        for item in analyses
    }
    position_by_role = {str(item["role"]): str(item.get("position")) for item in analyses}
    adjustment_by_role = {}
    reconciliation = decision.return_reconciliation
    if reconciliation is not None:
        adjustment_by_role = {item.role.value: item for item in reconciliation.adjustments}

    overlaps: list[dict[str, Any]] = []
    correlated_clusters: list[dict[str, Any]] = []
    roles = sorted(origins_by_role)
    for index, left in enumerate(roles):
        for right in roles[index + 1 :]:
            shared = tuple(sorted(origins_by_role[left].intersection(origins_by_role[right])))
            if not shared:
                continue
            record = {"left_role": left, "right_role": right, "shared_origins": list(shared)}
            overlaps.append(record)
            if (
                left in _DIRECTIONAL_ROLES
                and right in _DIRECTIONAL_ROLES
                and position_by_role.get(left) == position_by_role.get(right)
                and position_by_role.get(left) not in {"abstain", "neutral"}
            ):
                correlated_clusters.append(record)

    structured_context = _decision_context(decision)
    context_roles = {}
    if structured_context is not None:
        committee_context = structured_context.get("committee", {})
        if isinstance(committee_context, Mapping):
            for item in committee_context.get("roles", ()):
                if isinstance(item, Mapping) and item.get("role"):
                    context_roles[str(item["role"])] = item

    specialist_traces: list[dict[str, Any]] = []
    for analysis in analyses:
        role = str(analysis["role"])
        adjustment = adjustment_by_role.get(role)
        context_role = context_roles.get(role, {})
        overlap_roles = sorted(
            {
                item["right_role"] if item["left_role"] == role else item["left_role"]
                for item in overlaps
                if role in {item["left_role"], item["right_role"]}
            }
        )
        if role in _DIRECTIONAL_ROLES:
            effect = "Dependency-discounted return reconciliation, growth-stage alignment, CIO confidence, and target sizing."
        elif role == SpecialistRole.PORTFOLIO_RISK.value:
            effect = "Feasible ceiling, funding, implementation blocks, implementation confidence, and CIO target eligibility."
        else:
            effect = "Evidence vetoes, evidence-confidence ceiling, CIO eligibility, confidence, and target sizing."
        specialist_traces.append(
            {
                "role": role,
                "required_inputs": list(_ROLE_REQUIREMENTS[role]),
                "inputs_received": list(_received_inputs(role, candidate=candidate, context=context, portfolio=portfolio)),
                "missing_inputs": list(_missing_inputs(role, context=context)),
                "unique_contribution": _ROLE_CONTRIBUTION[role],
                "confidence_methodology": _CONFIDENCE_METHOD[role],
                "stale_and_missing_data_behavior": _STALE_MISSING_BEHAVIOR[role],
                "position": analysis.get("position"),
                "confidence": analysis.get("confidence"),
                "dependency_weight": context_role.get("dependency_weight"),
                "expected_return_impact": analysis.get("expected_return_impact"),
                "evidence_origin_identifiers": sorted(origins_by_role[role]),
                "overlapping_roles": overlap_roles,
                "overlap_discount": None if adjustment is None else adjustment.overlap_discount,
                "applied_return_impact": None if adjustment is None else adjustment.applied_impact,
                "conclusion": analysis.get("conclusion"),
                "limitations": list(_tuple_text(analysis.get("limitations"))),
                "change_conditions": list(_tuple_text(analysis.get("change_conditions"))),
                "veto_reasons": list(_tuple_text(analysis.get("veto_reasons"))),
                "implementation_blocks": list(_tuple_text(analysis.get("implementation_blocks"))),
                "explicit_veto_authority": role == SpecialistRole.EVIDENCE_GOVERNANCE.value,
                "implementation_block_authority": role == SpecialistRole.PORTFOLIO_RISK.value,
                "direct_portfolio_action_authority": False,
                "effect_on_cio_and_target": effect,
            }
        )

    sufficiency = _cio_information_sufficiency(
        candidate=candidate,
        decision=decision,
        packet_payload=packet_payload,
        portfolio=portfolio,
        decision_context=structured_context,
    )
    incomplete = tuple(
        item["name"]
        for item in sufficiency
        if item["status"] in {"missing", "partial"}
    )
    source_versions = () if manifest is None else manifest.source_versions
    manifest_evidence = () if manifest is None else manifest.evidence_identifiers
    final_target = None
    construction_identifier = None
    if construction is not None:
        final_target = dict(construction.target_weights).get(candidate.instrument.symbol)
        construction_identifier = construction.request_identifier

    portfolio_context = {
        "portfolio_identifier": portfolio.identifier,
        "portfolio_value": portfolio.portfolio_value,
        "cash_weight": portfolio.cash_weight,
        "cash_expected_return": portfolio.cash_expected_return,
        "positions": [
            {
                "symbol": item.symbol,
                "current_weight": item.current_weight,
                "expected_return": item.expected_return,
                "sector": item.sector,
                "correlation_bucket": item.correlation_bucket,
                "factor_loadings": [list(value) for value in item.factor_loadings],
                "minimum_weight": item.minimum_weight,
                "funding_eligible": item.funding_eligible,
            }
            for item in portfolio.positions
        ],
        "candidate_exposure_profiles": [
            {
                "candidate_identifier": item.candidate_identifier,
                "sector": item.sector,
                "correlation_bucket": item.correlation_bucket,
                "factor_loadings": [list(value) for value in item.factor_loadings],
            }
            for item in portfolio.exposure_profiles
        ],
        "eligible_universe_publication_identifier": portfolio.eligible_universe_publication_identifier,
        "scenario_set_identifier": None if portfolio.scenario_set is None else portfolio.scenario_set.identifier,
    }

    payload = {
        "decision_identifier": decision.identifier,
        "candidate_identifier": candidate.identifier,
        "symbol": candidate.instrument.symbol,
        "as_of": decision.as_of.isoformat(),
        "code_version": code_version,
        "source": {
            "manifest_evidence_identifiers": list(manifest_evidence),
            "candidate_evidence_identifiers": list(candidate.evidence_identifiers),
            "source_versions": [list(item) for item in source_versions],
        },
        "normalized_point_in_time_record": {
            "identifier": candidate.identifier,
            "schema_version": candidate.schema_version,
            "as_of": candidate.as_of.isoformat(),
            "decision_snapshot_identifier": snapshot.identifier,
            "fingerprint": snapshot.fingerprint,
        },
        "derived_metrics": {
            "net_expected_return": candidate.net_expected_return,
            "opportunity_edge": candidate.opportunity_edge,
            "expected_downside": candidate.expected_downside,
            "probability_of_success": candidate.probability_of_success,
            "evidence_score": candidate.evidence_quality.score,
            "evidence_ceiling": candidate.evidence_quality.ceiling,
            "liquidity_score": candidate.liquidity_score,
            "implementation_cost_return": candidate.implementation_cost_return,
        },
        "specialists": specialist_traces,
        "committee_synthesis": {
            "exact_role_count": len(analyses),
            "raw_directional_support_ratio": packet_payload.get("directional_support_ratio"),
            "dependency_adjusted_directional_support_ratio": packet_payload.get("independent_support_ratio"),
            "raw_median_confidence": packet_payload.get("median_confidence"),
            "dependency_adjusted_confidence": packet_payload.get("independent_confidence"),
            "raw_coverage_ratio": packet_payload.get("coverage_ratio"),
            "effective_directional_count": packet_payload.get("effective_directional_count"),
            "evidence_independence_ratio": packet_payload.get("evidence_independence_ratio"),
            "evidence_vetoes": list(_tuple_text(packet_payload.get("evidence_vetoes"))),
            "implementation_blocks": list(_tuple_text(packet_payload.get("implementation_blocks"))),
            "strongest_dissent": packet_payload.get("strongest_dissent"),
            "all_disagreement": [] if structured_context is None else structured_context.get("committee", {}).get("all_opposition", []),
            "all_abstentions": [] if structured_context is None else structured_context.get("committee", {}).get("all_abstentions", []),
            "pairwise_origin_overlaps": overlaps,
            "correlated_directional_clusters": correlated_clusters,
            "return_reconciliation_dependency_discounted": reconciliation is not None,
            "growth_ensemble_and_support_ratios_dependency_discounted": structured_context is not None,
            "cio_confidence_dependency_discounted": structured_context is not None,
            "correlated_opinions_partly_treated_as_independent": False if structured_context is not None else bool(correlated_clusters),
        },
        "cio_decision": {
            "schema_version": decision.schema_version,
            "action": decision.action.value,
            "expected_return": decision.expected_return,
            "decision_horizon_days": decision.decision_horizon_days,
            "final_confidence": decision.final_confidence,
            "recommended_position_weight": decision.recommended_position_weight,
            "funding_source": decision.funding_source,
            "best_alternative_identifier": decision.best_alternative_identifier,
            "effective_opportunity_cost": decision.effective_opportunity_cost,
            "thesis": decision.thesis,
            "rationale": decision.rationale,
            "supporting_evidence": list(decision.supporting_evidence),
            "contradictory_evidence": list(decision.contradictory_evidence),
            "key_assumptions": list(decision.key_assumptions),
            "catalysts": list(decision.catalysts),
            "risks": list(decision.risks),
            "invalidation_conditions": list(decision.invalidation_conditions),
            "monitoring_indicators": list(decision.monitoring_indicators),
            "review_at": decision.review_at.isoformat(),
            "evidence_vetoes": list(decision.evidence_vetoes),
            "implementation_blocks": list(decision.implementation_blocks),
            "dissent": None if decision.dissent is None else {
                "opposing_role": decision.dissent.opposing_role.value,
                "opposing_conclusion": decision.dissent.opposing_conclusion,
                "disagreement_reason": decision.dissent.disagreement_reason,
                "resolving_evidence": list(decision.dissent.resolving_evidence),
            },
            "self_contained_context": structured_context,
        },
        "portfolio_context": portfolio_context,
        "initial_target": decision.recommended_position_weight,
        "construction": {
            "request_identifier": construction_identifier,
            "final_target": final_target,
            "status": None if construction is None else construction.status.value,
            "target_cash_weight": None if construction is None else construction.target_cash_weight,
            "target_weights": [] if construction is None else [list(item) for item in construction.target_weights],
            "turnover": None if construction is None else construction.turnover,
            "estimated_cost_return": None if construction is None else construction.estimated_cost_return,
            "expected_return_improvement": None if construction is None else construction.expected_return_improvement,
            "blocks": [] if construction is None else list(construction.blocks),
        },
        "cio_information_sufficiency": list(sufficiency),
        "information_sufficiency_go_no_go": "go" if not incomplete else "no_go",
        "incomplete_information_categories": list(incomplete),
        "authority": {
            "diagnostic_only": True,
            "investment_behavior_changed": False,
            "cio_authority_changed": False,
            "construction_authority_changed": False,
            "execution_authority_changed": False,
            "real_money_authorized": False,
        },
    }
    return CommitteeCIOInformationTrace(payload=payload)


def append_committee_cio_information_trace(
    journal: SQLiteCIOJournal,
    trace: CommitteeCIOInformationTrace,
) -> CIOJournalEvent:
    return journal.append(
        event_type=CIOJournalEventType.COMMITTEE_CIO_INFORMATION_TRACE,
        aggregate_identifier=trace.decision_identifier,
        occurred_at=trace.as_of,
        payload=trace.to_dict(),
        schema_version=trace.schema_version,
        event_identifier=f"event:committee-cio-trace:{trace.decision_identifier}",
    )


__all__ = [
    "CommitteeCIOInformationTrace",
    "append_committee_cio_information_trace",
    "build_committee_cio_information_trace",
]
