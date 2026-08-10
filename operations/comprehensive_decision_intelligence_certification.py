"""Comprehensive certification of the Capital Intelligence decision process.

This report does not prove investment skill merely because software components exist.
It combines structural path readiness with empirical statistical evidence and keeps a
hard distinction between:

1. software/operational capability,
2. point-in-time empirical validation,
3. permission to make a public performance claim, and
4. investment authority.

Only the governed CIO may authorize paper capital. No certification produced here can
change strategy, thresholds, specialist weights, construction policy, or execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from evaluation.cio_statistical_certification import CIOStatisticalCertificationReport


class CertificationState(str, Enum):
    CERTIFIED = "certified"
    EMPIRICAL_EVIDENCE_PENDING = "empirical_evidence_pending"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class DecisionIntelligenceCertificationGate:
    name: str
    passed: bool
    evidence: tuple[str, ...]
    blocking: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("certification gate name cannot be empty")
        if self.passed and not self.evidence:
            raise ValueError("passed certification gates require evidence")


@dataclass(frozen=True, slots=True)
class ComprehensiveDecisionIntelligenceCertification:
    as_of: datetime
    state: CertificationState
    gates: tuple[DecisionIntelligenceCertificationGate, ...]
    blocking_failures: tuple[str, ...]
    empirical_pending: tuple[str, ...]
    statistically_certified: bool
    public_performance_claim_authorized: bool
    automatic_policy_promotion_authorized: bool = False
    investment_authority: bool = False
    real_money_authorized: bool = False
    schema_version: str = "comprehensive-decision-intelligence-certification.v1"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.automatic_policy_promotion_authorized or self.investment_authority or self.real_money_authorized:
            raise ValueError("certification cannot create investment, policy, or real-money authority")
        if self.public_performance_claim_authorized and self.state is not CertificationState.CERTIFIED:
            raise ValueError("performance claims require full certification")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "state": self.state.value,
            "gates": [
                {
                    "name": gate.name,
                    "passed": gate.passed,
                    "blocking": gate.blocking,
                    "evidence": list(gate.evidence),
                }
                for gate in self.gates
            ],
            "blocking_failures": list(self.blocking_failures),
            "empirical_pending": list(self.empirical_pending),
            "statistically_certified": self.statistically_certified,
            "public_performance_claim_authorized": self.public_performance_claim_authorized,
            "automatic_policy_promotion_authorized": False,
            "investment_authority": False,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }


def _gate(name: str, passed: bool, *evidence: str, blocking: bool = True) -> DecisionIntelligenceCertificationGate:
    cleaned = tuple(str(item).strip() for item in evidence if str(item).strip())
    if passed and not cleaned:
        cleaned = (f"{name} passed",)
    return DecisionIntelligenceCertificationGate(name, bool(passed), cleaned, blocking)


def build_comprehensive_decision_intelligence_certification(
    *,
    as_of: datetime,
    statistical_report: CIOStatisticalCertificationReport | None,
    information_gap_audit: Mapping[str, Any],
    all_market_runtime_certified: bool,
    six_specialist_path_certified: bool,
    cio_only_authority_certified: bool,
    construction_certified: bool,
    paper_execution_reconciliation_certified: bool,
    decision_explanation_certified: bool,
    causal_resolution_available: bool,
    expectations_resolution_available: bool,
    portfolio_risk_synthesis_available: bool,
    atomic_relative_value_execution_certified: bool,
    human_performance_claim_approval: bool = False,
) -> ComprehensiveDecisionIntelligenceCertification:
    """Combine path safety and empirical proof without conflating the two."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    unresolved_domains = tuple(
        str(item)
        for item in information_gap_audit.get("unresolved_domains", ())
        if str(item).strip()
    )
    decision_certified_domains = tuple(
        str(item)
        for item in information_gap_audit.get("decision_certified_domains", ())
        if str(item).strip()
    )
    statistical_certified = bool(
        statistical_report is not None and statistical_report.statistically_certified
    )
    gates = (
        _gate("all_market_runtime", all_market_runtime_certified, "capability-qualified all-market runtime exact-release certification"),
        _gate("six_specialist_path", six_specialist_path_certified, "exactly six advisory specialist analyses precede CIO authority"),
        _gate("cio_only_authority", cio_only_authority_certified, "CIO remains sole investment authority"),
        _gate("portfolio_construction", construction_certified, "canonical portfolio construction and sizing certified"),
        _gate("paper_execution_reconciliation", paper_execution_reconciliation_certified, "reconciled paper-only execution certified"),
        _gate("decision_explanation", decision_explanation_certified, "Decision Intelligence v3 evidence-to-decision explanation available"),
        _gate("causal_resolution", causal_resolution_available, "causal hypotheses persist and can be resolved point-in-time", blocking=False),
        _gate("expectations_resolution", expectations_resolution_available, "market/internal expectations persist and can be resolved point-in-time", blocking=False),
        _gate("portfolio_risk_synthesis", portfolio_risk_synthesis_available, "current-versus-proposed factor/stress synthesis available", blocking=False),
        _gate("atomic_relative_value_execution", atomic_relative_value_execution_certified, "atomic multi-leg paper implementation certified", blocking=False),
        _gate(
            "decision_information_depth",
            not unresolved_domains,
            *(decision_certified_domains or ("no unresolved decision-information domains",)),
            blocking=False,
        ),
        _gate(
            "statistical_edge",
            statistical_certified,
            *(
                (f"resolved decisions={statistical_report.resolved_decision_count}",)
                if statistical_report is not None
                else ("no statistically qualifying resolved CIO sample yet",)
            ),
            blocking=False,
        ),
    )
    blocking_failures = tuple(gate.name for gate in gates if gate.blocking and not gate.passed)
    empirical_pending = tuple(
        gate.name
        for gate in gates
        if not gate.blocking and not gate.passed
    )
    if blocking_failures:
        state = CertificationState.BLOCKED
    elif empirical_pending:
        state = CertificationState.EMPIRICAL_EVIDENCE_PENDING
    else:
        state = CertificationState.CERTIFIED
    performance_claim = bool(
        state is CertificationState.CERTIFIED
        and statistical_certified
        and human_performance_claim_approval
    )
    return ComprehensiveDecisionIntelligenceCertification(
        as_of=as_of,
        state=state,
        gates=gates,
        blocking_failures=blocking_failures,
        empirical_pending=empirical_pending,
        statistically_certified=statistical_certified,
        public_performance_claim_authorized=performance_claim,
    )


__all__ = [
    "CertificationState",
    "ComprehensiveDecisionIntelligenceCertification",
    "DecisionIntelligenceCertificationGate",
    "build_comprehensive_decision_intelligence_certification",
]
