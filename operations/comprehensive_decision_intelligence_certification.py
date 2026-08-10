"""Comprehensive structural + empirical certification of the CIO decision process."""
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
            raise ValueError("passed gates require evidence")


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
            raise ValueError("certification cannot create policy, investment, or real-money authority")
        if self.public_performance_claim_authorized and self.state is not CertificationState.CERTIFIED:
            raise ValueError("performance claims require full certification")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "state": self.state.value,
            "gates": [
                {"name": item.name, "passed": item.passed, "blocking": item.blocking, "evidence": list(item.evidence)}
                for item in self.gates
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
    return DecisionIntelligenceCertificationGate(
        name=name,
        passed=bool(passed),
        evidence=cleaned or ((f"{name} passed",) if passed else ()),
        blocking=blocking,
    )


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
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    unresolved = tuple(str(item) for item in information_gap_audit.get("unresolved_domains", ()) if str(item).strip())
    certified_domains = tuple(str(item) for item in information_gap_audit.get("decision_certified_domains", ()) if str(item).strip())
    statistical_certified = bool(statistical_report is not None and statistical_report.statistically_certified)
    gates = (
        _gate("all_market_runtime", all_market_runtime_certified, "capability-qualified all-market exact-release certification"),
        _gate("six_specialist_path", six_specialist_path_certified, "exactly six advisory specialists precede CIO"),
        _gate("cio_only_authority", cio_only_authority_certified, "CIO remains sole investment authority"),
        _gate("portfolio_construction", construction_certified, "canonical portfolio construction certified"),
        _gate("paper_execution_reconciliation", paper_execution_reconciliation_certified, "reconciled paper-only implementation certified"),
        _gate("decision_explanation", decision_explanation_certified, "Decision Intelligence evidence-to-decision explanation available"),
        _gate("causal_resolution", causal_resolution_available, "causal hypotheses persist and resolve PIT", blocking=False),
        _gate("expectations_resolution", expectations_resolution_available, "expectations persist and resolve PIT", blocking=False),
        _gate("portfolio_risk_synthesis", portfolio_risk_synthesis_available, "current-versus-proposed portfolio stress synthesis available", blocking=False),
        _gate("atomic_relative_value_execution", atomic_relative_value_execution_certified, "atomic multi-leg paper implementation certified", blocking=False),
        _gate("decision_information_depth", not unresolved, *(certified_domains or ("no unresolved decision-information domains",)), blocking=False),
        _gate(
            "statistical_edge",
            statistical_certified,
            *( (f"resolved decisions={statistical_report.resolved_decision_count}",) if statistical_report is not None else ("statistically qualifying resolved CIO sample not yet available",) ),
            blocking=False,
        ),
    )
    blocking_failures = tuple(item.name for item in gates if item.blocking and not item.passed)
    empirical_pending = tuple(item.name for item in gates if not item.blocking and not item.passed)
    state = (
        CertificationState.BLOCKED
        if blocking_failures
        else CertificationState.EMPIRICAL_EVIDENCE_PENDING
        if empirical_pending
        else CertificationState.CERTIFIED
    )
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
