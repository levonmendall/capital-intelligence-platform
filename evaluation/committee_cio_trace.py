"""Audit-only trace of evidence through specialists, committee, and CIO.

The trace consumes already-completed canonical records.  It cannot alter a
specialist analysis, synthesize an action, size a position, construct a
portfolio, or authorize execution.
"""

from __future__ import annotations

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
    SpecialistRole.MACRO_ECONOMIC.value: "Uses the governed macro-context confidence, then applies the historical-learning ceiling.",
    SpecialistRole.MARKET.value: "Uses the governed market-context confidence, then applies the historical-learning ceiling.",
    SpecialistRole.CROSS_ASSET_FORECAST.value: "Minimum of aggregate confidence, calibration, agreement, stability, and horizon alignment, then the historical-learning ceiling.",
    SpecialistRole.FUNDAMENTAL_VALUATION.value: "Asset valuation confidence, or the minimum of company, quality-factor, and valuation-factor confidence, then the historical-learning ceiling.",
    SpecialistRole.PORTFOLIO_RISK.value: "Weakest candidate evidence dimension when feasible; otherwise 40%, then the historical-learning ceiling.",
    SpecialistRole.EVIDENCE_GOVERNANCE.value: "Weakest candidate evidence dimension, then the historical-learning ceiling.",
}

_STALE_MISSING_BEHAVIOR = {
    SpecialistRole.MACRO_ECONOMIC.value: "Production context must exist; specialist output itself does not independently recheck macro age.",
    SpecialistRole.MARKET.value: "Production context must exist; global market staleness is enforced by the evidence-governance role using candidate market-data age.",
    SpecialistRole.CROSS_ASSET_FORECAST.value: "Missing or failed forecast quality causes abstention and zero return impact.",
    SpecialistRole.FUNDAMENTAL_VALUATION.value: "Missing required company or asset valuation causes abstention; U.S. equity absence also creates an evidence veto.",
    SpecialistRole.PORTFOLIO_RISK.value: "Missing feasible size causes abstention; explicit implementation blocks cause opposition.",
    SpecialistRole.EVIDENCE_GOVERNANCE.value: "Low quality, stale market data, missing identifiers/models, or invalid timing produces an explicit categorized veto.",
}


def _tuple_text(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


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
) -> tuple[dict[str, Any], ...]:
    has_valuation = any(
        item.get("role") == SpecialistRole.FUNDAMENTAL_VALUATION.value
        and item.get("position") != "abstain"
        for item in packet_payload.get("analyses", ())
        if isinstance(item, Mapping)
    )
    return (
        _input_status("expected return and horizon", "present_structured", ("decision.expected_return", "decision.decision_horizon_days")),
        _input_status("return distribution and uncertainty", "present_structured", ("candidate.scenario_distribution", "decision.return_reconciliation")),
        _input_status("downside and tail risk", "present_structured", ("candidate.expected_downside", "reconciled outcomes", "robust/stressed controls")),
        _input_status("cash-relative attractiveness", "present_structured", ("best alternative", "effective opportunity cost", "robust edge")),
        _input_status("benchmark-relative attractiveness", "missing", ("No approved benchmark-relative field enters CIO synthesis.",)),
        _input_status("valuation", "present_upstream_only" if has_valuation else "missing", ("fundamental/valuation specialist analysis",)),
        _input_status("fundamentals", "present_upstream_only" if has_valuation else "not_applicable_or_missing", ("fundamental/valuation specialist analysis",)),
        _input_status("technical condition", "present_upstream_only", ("market specialist analysis",)),
        _input_status("catalysts and disconfirming evidence", "present_structured", ("candidate.primary_catalysts", "candidate.contradictory_evidence")),
        _input_status("liquidity and costs", "present_structured", ("candidate.liquidity_score", "transaction and slippage costs")),
        _input_status("data limitations", "present_upstream_only", ("specialist limitations are available in the packet but not preserved in full on the CIO decision",)),
        _input_status("specialist agreement and disagreement", "partial", ("full packet positions", "directional ratios", "only strongest dissent is preserved on the decision")),
        _input_status("portfolio correlation and diversification effect", "partial", ("portfolio preview and exposure profile", "decision portfolio impact is narrative")),
        _input_status("current exposures and available risk budget", "partial", (f"positions={len(portfolio.positions)}", f"cash_weight={portfolio.cash_weight:.8f}", "not frozen as a structured CIO-output field")),
        _input_status("proposed risk-adjusted initial target", "present_structured", ("decision.recommended_position_weight",)),
        _input_status("conditions for increasing, reducing, and exiting", "partial", ("invalidation and monitoring conditions", "policy thresholds are not emitted as a structured action ladder")),
    )


@dataclass(frozen=True, slots=True)
class CommitteeCIOInformationTrace:
    payload: Mapping[str, Any]
    schema_version: str = "committee-cio-information-trace.v1"

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

    specialist_traces: list[dict[str, Any]] = []
    for analysis in analyses:
        role = str(analysis["role"])
        adjustment = adjustment_by_role.get(role)
        overlap_roles = sorted(
            {
                item["right_role"] if item["left_role"] == role else item["left_role"]
                for item in overlaps
                if role in {item["left_role"], item["right_role"]}
            }
        )
        if role in _DIRECTIONAL_ROLES:
            effect = "Return reconciliation, growth-stage alignment, CIO confidence, and potentially target sizing."
        elif role == SpecialistRole.PORTFOLIO_RISK.value:
            effect = "Feasible ceiling, funding, implementation blocks, implementation confidence, and CIO target eligibility."
        else:
            effect = "Evidence vetoes, evidence-confidence ceiling, CIO eligibility, confidence, and target sizing."
        specialist_traces.append(
            {
                "role": role,
                "required_inputs": list(_ROLE_REQUIREMENTS[role]),
                "inputs_received": list(
                    _received_inputs(role, candidate=candidate, context=context, portfolio=portfolio)
                ),
                "missing_inputs": list(_missing_inputs(role, context=context)),
                "unique_contribution": _ROLE_CONTRIBUTION[role],
                "confidence_methodology": _CONFIDENCE_METHOD[role],
                "stale_and_missing_data_behavior": _STALE_MISSING_BEHAVIOR[role],
                "position": analysis.get("position"),
                "confidence": analysis.get("confidence"),
                "expected_return_impact": analysis.get("expected_return_impact"),
                "evidence_origin_identifiers": sorted(origins_by_role[role]),
                "overlapping_roles": overlap_roles,
                "overlap_discount": None if adjustment is None else adjustment.overlap_discount,
                "applied_return_impact": None if adjustment is None else adjustment.applied_impact,
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
            "directional_support_ratio": packet_payload.get("directional_support_ratio"),
            "median_confidence": packet_payload.get("median_confidence"),
            "coverage_ratio": packet_payload.get("coverage_ratio"),
            "evidence_vetoes": list(_tuple_text(packet_payload.get("evidence_vetoes"))),
            "implementation_blocks": list(_tuple_text(packet_payload.get("implementation_blocks"))),
            "strongest_dissent": packet_payload.get("strongest_dissent"),
            "pairwise_origin_overlaps": overlaps,
            "correlated_directional_clusters": correlated_clusters,
            "return_reconciliation_dependency_discounted": reconciliation is not None,
            "growth_ensemble_and_support_ratios_dependency_discounted": False,
            "correlated_opinions_partly_treated_as_independent": bool(correlated_clusters),
        },
        "cio_decision": {
            "action": decision.action.value,
            "expected_return": decision.expected_return,
            "decision_horizon_days": decision.decision_horizon_days,
            "final_confidence": decision.final_confidence,
            "recommended_position_weight": decision.recommended_position_weight,
            "evidence_vetoes": list(decision.evidence_vetoes),
            "implementation_blocks": list(decision.implementation_blocks),
            "dissent": None if decision.dissent is None else decision.dissent.opposing_role.value,
        },
        "initial_target": decision.recommended_position_weight,
        "construction": {
            "request_identifier": construction_identifier,
            "final_target": final_target,
            "status": None if construction is None else construction.status.value,
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
