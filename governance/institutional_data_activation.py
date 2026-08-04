"""Governed institutional-data activation program.

A dataset remains disabled until every licensing, point-in-time, provenance, identity,
freshness, outage, fixture, certification, and fail-closed production-binding gate is
explicitly satisfied. An API response alone is never activation evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class InstitutionalDataTier(str, Enum):
    A = "tier_a_highest_immediate_decision_value"
    B = "tier_b_portfolio_exposure_and_market_structure"
    C = "tier_c_specialized_markets"


class InstitutionalDataset(str, Enum):
    CONSENSUS_EARNINGS = "consensus_earnings_estimates_and_revisions"
    CONSENSUS_MACRO = "consensus_macro_expectations_and_surprises"
    FUND_FLOWS = "etf_and_mutual_fund_flows"
    CREDIT_MARKETS = "credit_spreads_curves_issuance_and_liquidity"
    OPTIONS = "options_volatility_surfaces_skew_and_positioning"
    FUTURES_POSITIONING = "futures_open_interest_and_cftc_positioning"
    SECURITY_MASTER = "historical_security_master_and_corporate_actions"
    SHORT_INTEREST = "short_interest_and_securities_lending"
    INSTITUTIONAL_OWNERSHIP = "institutional_ownership_changes"
    CROSS_BORDER_FLOWS = "cross_border_capital_flows"
    CORPORATE_FLOWS = "buybacks_issuance_and_insider_transactions"
    GLOBAL_FIXED_INCOME = "global_fixed_income_pricing_and_duration"
    CRYPTO_EXCHANGE_FLOWS = "crypto_exchange_flows"
    STABLECOIN = "stablecoin_supply_and_movement"
    CRYPTO_DERIVATIVES = "crypto_funding_open_interest_and_liquidations"
    DEALER_POSITIONING = "dealer_positioning"
    SUPPLY_CHAIN = "supply_chain_and_industry_data"
    ALTERNATIVE_DATA = "validated_alternative_datasets"


class DatasetActivationState(str, Enum):
    DISABLED = "disabled"
    BLOCKED = "blocked"
    CERTIFIED_SHADOW = "certified_shadow"
    ACTIVE_ADVISORY = "active_advisory"


_TIER_ORDER: dict[InstitutionalDataTier, tuple[InstitutionalDataset, ...]] = {
    InstitutionalDataTier.A: (
        InstitutionalDataset.CONSENSUS_EARNINGS,
        InstitutionalDataset.CONSENSUS_MACRO,
        InstitutionalDataset.FUND_FLOWS,
        InstitutionalDataset.CREDIT_MARKETS,
        InstitutionalDataset.OPTIONS,
        InstitutionalDataset.FUTURES_POSITIONING,
    ),
    InstitutionalDataTier.B: (
        InstitutionalDataset.SECURITY_MASTER,
        InstitutionalDataset.SHORT_INTEREST,
        InstitutionalDataset.INSTITUTIONAL_OWNERSHIP,
        InstitutionalDataset.CROSS_BORDER_FLOWS,
        InstitutionalDataset.CORPORATE_FLOWS,
        InstitutionalDataset.GLOBAL_FIXED_INCOME,
    ),
    InstitutionalDataTier.C: (
        InstitutionalDataset.CRYPTO_EXCHANGE_FLOWS,
        InstitutionalDataset.STABLECOIN,
        InstitutionalDataset.CRYPTO_DERIVATIVES,
        InstitutionalDataset.DEALER_POSITIONING,
        InstitutionalDataset.SUPPLY_CHAIN,
        InstitutionalDataset.ALTERNATIVE_DATA,
    ),
}


@dataclass(frozen=True, slots=True)
class ProviderOnboardingGates:
    licensing_review: bool
    allowed_use_and_retention_review: bool
    historical_point_in_time_coverage: bool
    provenance_complete: bool
    symbol_identity_reconciliation: bool
    freshness_and_sla_policy: bool
    outage_behavior: bool
    deterministic_fixtures: bool
    certification_scenarios: bool
    data_readiness_activation: bool
    fail_closed_production_binding: bool

    @property
    def passed(self) -> bool:
        return all(
            (
                self.licensing_review,
                self.allowed_use_and_retention_review,
                self.historical_point_in_time_coverage,
                self.provenance_complete,
                self.symbol_identity_reconciliation,
                self.freshness_and_sla_policy,
                self.outage_behavior,
                self.deterministic_fixtures,
                self.certification_scenarios,
                self.data_readiness_activation,
                self.fail_closed_production_binding,
            )
        )

    def missing(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "licensing_review",
                "allowed_use_and_retention_review",
                "historical_point_in_time_coverage",
                "provenance_complete",
                "symbol_identity_reconciliation",
                "freshness_and_sla_policy",
                "outage_behavior",
                "deterministic_fixtures",
                "certification_scenarios",
                "data_readiness_activation",
                "fail_closed_production_binding",
            )
            if not getattr(self, name)
        )


@dataclass(frozen=True, slots=True)
class InstitutionalDatasetActivation:
    identifier: str
    dataset: InstitutionalDataset
    provider_identifier: str
    assessed_at: datetime
    gates: ProviderOnboardingGates
    requested_state: DatasetActivationState
    certification_identifier: str | None = None
    limitations: tuple[str, ...] = ()
    schema_version: str = "institutional-dataset-activation.v1"

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.provider_identifier.strip():
            raise ValueError("activation and provider identifiers are required")
        if self.assessed_at.tzinfo is None or self.assessed_at.utcoffset() is None:
            raise ValueError("assessed_at must be timezone-aware")
        if self.requested_state in {
            DatasetActivationState.CERTIFIED_SHADOW,
            DatasetActivationState.ACTIVE_ADVISORY,
        }:
            if not self.gates.passed:
                raise ValueError(
                    "dataset cannot be enabled before all onboarding gates pass: "
                    + ", ".join(self.gates.missing())
                )
            if (
                self.certification_identifier is None
                or not self.certification_identifier.strip()
            ):
                raise ValueError("enabled datasets require certification_identifier")

    @property
    def effective_state(self) -> DatasetActivationState:
        if self.requested_state is DatasetActivationState.DISABLED:
            return DatasetActivationState.DISABLED
        if not self.gates.passed:
            return DatasetActivationState.BLOCKED
        return self.requested_state

    @property
    def production_decision_authorized(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "dataset": self.dataset.value,
            "tier": dataset_tier(self.dataset).value,
            "provider_identifier": self.provider_identifier,
            "assessed_at": self.assessed_at.isoformat(),
            "requested_state": self.requested_state.value,
            "effective_state": self.effective_state.value,
            "certification_identifier": self.certification_identifier,
            "missing_gates": list(self.gates.missing()),
            "limitations": list(self.limitations),
            "production_decision_authorized": False,
            "real_money_authorized": False,
        }


def dataset_tier(dataset: InstitutionalDataset) -> InstitutionalDataTier:
    for tier, datasets in _TIER_ORDER.items():
        if dataset in datasets:
            return tier
    raise ValueError(f"dataset tier is not defined for {dataset!r}")


def recommended_activation_order() -> tuple[InstitutionalDataset, ...]:
    return tuple(
        dataset
        for tier in InstitutionalDataTier
        for dataset in _TIER_ORDER[tier]
    )


def disabled_activation_inventory(
    *,
    assessed_at: datetime,
) -> tuple[InstitutionalDatasetActivation, ...]:
    """Return the truthful default inventory when no commercial license is approved."""

    gates = ProviderOnboardingGates(*(False for _ in range(11)))
    return tuple(
        InstitutionalDatasetActivation(
            identifier=f"institutional-data:{dataset.value}:disabled",
            dataset=dataset,
            provider_identifier="unconfigured",
            assessed_at=assessed_at,
            gates=gates,
            requested_state=DatasetActivationState.DISABLED,
            limitations=(
                "No licensed, configured, and certified provider is active.",
            ),
        )
        for dataset in recommended_activation_order()
    )


__all__ = [
    "DatasetActivationState",
    "InstitutionalDataTier",
    "InstitutionalDataset",
    "InstitutionalDatasetActivation",
    "ProviderOnboardingGates",
    "dataset_tier",
    "disabled_activation_inventory",
    "recommended_activation_order",
]
