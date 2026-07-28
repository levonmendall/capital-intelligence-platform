"""All-markets data-readiness assessment and report models."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from cio.models import CandidateAssetClass
from governance.data_readiness_core import DataDomain, DataReadinessError, MarketDataScopeState

@dataclass(frozen=True, slots=True)
class DatasetReadinessAssessment:
    asset_class: CandidateAssetClass
    market_state: MarketDataScopeState
    domain: DataDomain
    required_provider_identifiers: tuple[str, ...]
    ready_provider_identifiers: tuple[str, ...]
    minimum_ready_providers: int
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return len(self.ready_provider_identifiers) >= self.minimum_ready_providers

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class.value,
            "market_state": self.market_state.value,
            "domain": self.domain.value,
            "required_provider_identifiers": list(self.required_provider_identifiers),
            "ready_provider_identifiers": list(self.ready_provider_identifiers),
            "minimum_ready_providers": self.minimum_ready_providers,
            "ready": self.ready,
            "blockers": list(self.blockers),
        }

@dataclass(frozen=True, slots=True)
class MarketDataReadinessAssessment:
    asset_class: CandidateAssetClass
    state: MarketDataScopeState
    rationale: str
    datasets: tuple[DatasetReadinessAssessment, ...]

    @property
    def ready(self) -> bool:
        if self.state is MarketDataScopeState.PROHIBITED:
            return True
        return bool(self.datasets) and all(item.ready for item in self.datasets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class.value,
            "scope_state": self.state.value,
            "rationale": self.rationale,
            "ready": self.ready,
            "datasets": [item.to_dict() for item in self.datasets],
        }

@dataclass(frozen=True, slots=True)
class AllMarketsDataReadinessReport:
    manifest_identifier: str
    schema_version: str
    reporting_currency: str
    state: AllMarketsDataReadinessState
    all_candidate_markets_declared: bool
    global_test_data_ready: bool
    paper_eligible_data_ready: bool
    decision_relevant_data_ready: bool
    evidence_only_data_ready: bool
    missing_environment_variables: tuple[str, ...]
    markets: tuple[MarketDataReadinessAssessment, ...]
    blockers: tuple[str, ...]
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if self.real_money_authorized:
            raise ValueError("data readiness cannot authorize real-money trading")

    @property
    def evidence_identifier(self) -> str:
        return f"all-markets-data-readiness:{self.manifest_identifier}:{self.state.value}"

    def to_readiness_gate_certification(
        self,
        *,
        identifier: str,
        certified_at: "datetime",
        effective_at: "datetime",
        expires_at: "datetime",
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        authority_identifiers: tuple[str, ...],
        limitations: tuple[str, ...] = (),
        additional_evidence_identifiers: tuple[str, ...] = (),
    ) -> "ReadinessGateCertification":
        """Build the certified-data gate only from ready governed evidence.

        Additional evidence allows the market-data report to be bound to separate
        readiness authorities such as maximum decision-information coverage.
        Persistence remains an explicit governance action.
        """
        if not self.global_test_data_ready:
            raise DataReadinessError(
                "cannot certify the product data gate while all-markets data readiness is incomplete"
            )
        if not isinstance(additional_evidence_identifiers, tuple) or not all(
            isinstance(item, str) and item.strip() for item in additional_evidence_identifiers
        ):
            raise TypeError("additional_evidence_identifiers must contain non-empty strings")
        from governance.readiness_evidence import (
            ReadinessGate,
            ReadinessGateCertification,
            ReadinessGateState,
        )

        scope_limitations = tuple(
            f"{item.asset_class.value}: {item.state.value}"
            for item in self.markets
            if item.state is not MarketDataScopeState.PROHIBITED
        )
        evidence = tuple(
            dict.fromkeys(
                (
                    self.evidence_identifier,
                    self.manifest_identifier,
                    *additional_evidence_identifiers,
                )
            )
        )
        return ReadinessGateCertification(
            identifier=identifier,
            gate=ReadinessGate.CERTIFIED_DATA,
            state=ReadinessGateState.SATISFIED,
            certified_at=certified_at,
            effective_at=effective_at,
            expires_at=expires_at,
            baseline_identifier=baseline_identifier,
            process_version=process_version,
            code_version=code_version,
            evidence_identifiers=evidence,
            authority_identifiers=authority_identifiers,
            limitations=scope_limitations + limitations,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "all-markets-data-readiness-report.v1",
            "manifest_identifier": self.manifest_identifier,
            "manifest_schema_version": self.schema_version,
            "reporting_currency": self.reporting_currency,
            "state": self.state.value,
            "all_candidate_markets_declared": self.all_candidate_markets_declared,
            "global_test_data_ready": self.global_test_data_ready,
            "paper_eligible_data_ready": self.paper_eligible_data_ready,
            "decision_relevant_data_ready": self.decision_relevant_data_ready,
            "evidence_only_data_ready": self.evidence_only_data_ready,
            "missing_environment_variables": list(self.missing_environment_variables),
            "blockers": list(self.blockers),
            "markets": [item.to_dict() for item in self.markets],
            "evidence_identifier": self.evidence_identifier,
            "real_money_authorized": False,
        }
