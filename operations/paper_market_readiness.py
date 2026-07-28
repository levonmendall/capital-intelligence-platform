"""Repository-internal and activation readiness for universal paper markets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio import CandidateAssetClass
from governance.asset_class_scope import (
    AssetClassApprovalState,
    SQLiteAssetClassApprovalStore,
    UNIVERSAL_GOVERNED_ASSET_CLASSES,
)
from governance.data_readiness import (
    AllMarketsDataManifest,
    AllMarketsDataReadinessEvaluator,
    DataDomain,
    MarketDataScopeState,
)
from governance.decision_information_activation import (
    DecisionInformationActivationAuthority,
    SQLiteDecisionInformationActivationStore,
)
from governance.decision_information_readiness import (
    MaximumDecisionInformationManifest,
    MaximumDecisionInformationReadinessEvaluator,
)
from governance.provider_activation import (
    ProviderActivationAuthority,
    SQLiteProviderActivationStore,
)
from portfolio.multi_asset_controls import MultiAssetConstructionPolicy
from portfolio.multi_asset_execution import MultiAssetExecutionPolicy
from providers.configured_dataset import ConfiguredDatasetProviderSettings
from data.provider_dataset import ProviderDatasetType


DATA_DOMAIN_DATASET_TYPE: Mapping[DataDomain, ProviderDatasetType] = {
    DataDomain.SECURITY_MASTER: ProviderDatasetType.SECURITY_MASTER,
    DataDomain.MARKET_PRICES: ProviderDatasetType.MARKET_PRICES,
    DataDomain.QUOTES_LIQUIDITY: ProviderDatasetType.QUOTES_LIQUIDITY,
    DataDomain.CORPORATE_ACTIONS: ProviderDatasetType.CORPORATE_ACTIONS,
    DataDomain.FUNDAMENTALS: ProviderDatasetType.FUNDAMENTALS,
    DataDomain.FILINGS: ProviderDatasetType.FILINGS,
    DataDomain.MACRO: ProviderDatasetType.MACRO,
    DataDomain.FX_RATES: ProviderDatasetType.FX_RATES,
    DataDomain.FIXED_INCOME_TERMS: ProviderDatasetType.FIXED_INCOME_TERMS,
    DataDomain.CRYPTO_MARKET_STRUCTURE: (
        ProviderDatasetType.CRYPTO_MARKET_STRUCTURE
    ),
    DataDomain.COMMODITY_CURVES: ProviderDatasetType.COMMODITY_CURVES,
    DataDomain.DERIVATIVE_CONTRACTS: ProviderDatasetType.DERIVATIVE_CONTRACTS,
    DataDomain.MARGIN_COLLATERAL: ProviderDatasetType.MARGIN_COLLATERAL,
    DataDomain.VOLATILITY_SURFACES: ProviderDatasetType.VOLATILITY_SURFACES,
    DataDomain.MARKET_CALENDARS: ProviderDatasetType.MARKET_CALENDARS,
    DataDomain.BENCHMARKS: ProviderDatasetType.BENCHMARKS,
    DataDomain.EXECUTION_INPUTS: ProviderDatasetType.EXECUTION_INPUTS,
}

CANONICAL_PIPELINE_DATASET_TYPES = frozenset(
    {
        ProviderDatasetType.SECURITY_MASTER,
        ProviderDatasetType.QUOTES_LIQUIDITY,
        ProviderDatasetType.CANDIDATE_SCREENING,
        ProviderDatasetType.DECISION_INFORMATION,
    }
)


@dataclass(frozen=True, slots=True)
class UniversalPaperMarketReadinessReport:
    evaluated_at: datetime
    internal_ready: bool
    paper_ready: bool
    market_data_ready: bool
    decision_information_ready: bool
    required_market_classes: tuple[str, ...]
    active_approval_classes: tuple[str, ...]
    activated_provider_identifiers: tuple[str, ...]
    activated_decision_information_identifiers: tuple[str, ...]
    configured_provider_identifiers: tuple[str, ...]
    internal_blockers: tuple[str, ...]
    external_blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "universal-paper-market-readiness.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "internal_ready": self.internal_ready,
            "paper_ready": self.paper_ready,
            "market_data_ready": self.market_data_ready,
            "decision_information_ready": self.decision_information_ready,
            "required_market_classes": list(self.required_market_classes),
            "active_approval_classes": list(self.active_approval_classes),
            "activated_provider_identifiers": list(
                self.activated_provider_identifiers
            ),
            "activated_decision_information_identifiers": list(
                self.activated_decision_information_identifiers
            ),
            "configured_provider_identifiers": list(
                self.configured_provider_identifiers
            ),
            "internal_blockers": list(self.internal_blockers),
            "external_blockers": list(self.external_blockers),
            "real_money_authorized": False,
        }


def _load_binding(path: str | Path) -> ConfiguredDatasetProviderSettings:
    import json

    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"provider binding {str(source)!r} must be an object")
    return ConfiguredDatasetProviderSettings.from_dict(payload)


def assess_universal_paper_market_readiness(
    *,
    manifest: AllMarketsDataManifest,
    information_manifest: MaximumDecisionInformationManifest,
    evaluated_at: datetime,
    environment: Mapping[str, str],
    provider_activation_store: SQLiteProviderActivationStore,
    decision_information_activation_store: SQLiteDecisionInformationActivationStore,
    asset_class_approval_store: SQLiteAssetClassApprovalStore,
    provider_binding_paths: Sequence[str | Path] = (),
) -> UniversalPaperMarketReadinessReport:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    internal_blockers: list[str] = []
    external_blockers: list[str] = []

    expected_market_classes = set(CandidateAssetClass) - {
        CandidateAssetClass.OTHER
    }
    declared_paper = {
        item.asset_class
        for item in manifest.markets
        if item.state is MarketDataScopeState.PAPER_ELIGIBLE
    }
    if declared_paper != expected_market_classes:
        internal_blockers.append(
            "paper-eligible manifest scope does not exactly cover every classified market"
        )
    other = tuple(
        item for item in manifest.markets if item.asset_class is CandidateAssetClass.OTHER
    )
    if len(other) != 1 or other[0].state is not MarketDataScopeState.PROHIBITED:
        internal_blockers.append("unclassified instruments must fail closed")

    required_domains = {
        requirement.domain
        for market in manifest.markets
        for requirement in market.requirements
    }
    missing_dataset_types = sorted(
        item.value for item in required_domains - set(DATA_DOMAIN_DATASET_TYPE)
    )
    if missing_dataset_types:
        internal_blockers.append(
            "provider-neutral dataset connector lacks domains: "
            + ", ".join(missing_dataset_types)
        )

    execution_policy = MultiAssetExecutionPolicy()
    construction_policy = MultiAssetConstructionPolicy()
    for asset_class in sorted(
        UNIVERSAL_GOVERNED_ASSET_CLASSES, key=lambda item: item.value
    ):
        try:
            execution_policy.session_model(asset_class)
            execution_policy.commission_bps(asset_class)
            construction_policy.class_limit(asset_class)
        except Exception as error:
            internal_blockers.append(
                f"{asset_class.value} implementation policy is incomplete: {error}"
            )

    settings = tuple(_load_binding(path) for path in provider_binding_paths)
    configured_provider_ids = tuple(
        sorted({item.provider_identifier for item in settings})
    )
    binding_types: dict[str, set[ProviderDatasetType]] = {}
    for item in settings:
        binding_types.setdefault(item.provider_identifier, set()).update(
            binding.dataset_type for binding in item.bindings
        )
    configured_dataset_types = {
        dataset_type
        for provider_types in binding_types.values()
        for dataset_type in provider_types
    }
    missing_pipeline_types = sorted(
        item.value
        for item in CANONICAL_PIPELINE_DATASET_TYPES - configured_dataset_types
    )
    if missing_pipeline_types:
        external_blockers.append(
            "canonical runtime bindings are missing datasets: "
            + ", ".join(missing_pipeline_types)
        )

    overlay = ProviderActivationAuthority(provider_activation_store).overlay(
        manifest, evaluated_at=evaluated_at
    )
    data_report = AllMarketsDataReadinessEvaluator().evaluate(
        overlay.manifest, environment=environment
    )
    information_overlay = DecisionInformationActivationAuthority(
        decision_information_activation_store
    ).overlay(information_manifest, evaluated_at=evaluated_at)
    information_report = MaximumDecisionInformationReadinessEvaluator().evaluate(
        information_overlay.manifest, environment=environment
    )
    active_provider_ids = set(overlay.activation_identifiers)
    for provider in overlay.manifest.providers:
        if not provider.enabled:
            continue
        configured = binding_types.get(provider.identifier)
        if configured is None:
            external_blockers.append(
                f"{provider.identifier}: no runtime dataset binding is configured"
            )
            continue
        required_types = {
            DATA_DOMAIN_DATASET_TYPE[domain] for domain in provider.domains
        }
        missing_types = sorted(
            item.value for item in required_types - configured
        )
        if missing_types:
            external_blockers.append(
                f"{provider.identifier}: binding lacks datasets: "
                + ", ".join(missing_types)
            )
    for source in information_overlay.manifest.sources:
        if not source.enabled:
            continue
        configured = binding_types.get(source.identifier)
        if configured is None:
            external_blockers.append(
                f"{source.identifier}: no decision-information runtime binding is configured"
            )
        elif ProviderDatasetType.DECISION_INFORMATION not in configured:
            external_blockers.append(
                f"{source.identifier}: binding lacks decision_information"
            )
    if not overlay.activation_identifiers:
        external_blockers.append("no runtime provider activations are active")
    if not information_overlay.activation_identifiers:
        external_blockers.append(
            "no runtime decision-information source activations are active"
        )

    active_approval_classes: list[str] = []
    for asset_class in sorted(
        UNIVERSAL_GOVERNED_ASSET_CLASSES, key=lambda item: item.value
    ):
        approvals = asset_class_approval_store.active_approvals(
            asset_class, evaluated_at=evaluated_at
        )
        if any(
            item.profile.state is AssetClassApprovalState.PAPER_ELIGIBLE
            and item.profile.paper_eligible
            for item in approvals
        ):
            active_approval_classes.append(asset_class.value)
        else:
            external_blockers.append(
                f"{asset_class.value}: no active complete paper-eligibility approval"
            )

    if not data_report.global_test_data_ready:
        external_blockers.extend(
            f"market-data: {item}" for item in data_report.blockers
        )
    if not information_report.all_domains_ready:
        external_blockers.extend(
            f"decision-information: {item}"
            for item in information_report.blockers
        )

    internal_ready = not internal_blockers
    paper_ready = internal_ready and not external_blockers
    return UniversalPaperMarketReadinessReport(
        evaluated_at=evaluated_at,
        internal_ready=internal_ready,
        paper_ready=paper_ready,
        market_data_ready=data_report.global_test_data_ready,
        decision_information_ready=information_report.all_domains_ready,
        required_market_classes=tuple(
            sorted(item.value for item in expected_market_classes)
        ),
        active_approval_classes=tuple(active_approval_classes),
        activated_provider_identifiers=tuple(
            sorted(overlay.activation_identifiers)
        ),
        activated_decision_information_identifiers=tuple(
            sorted(information_overlay.activation_identifiers)
        ),
        configured_provider_identifiers=configured_provider_ids,
        internal_blockers=tuple(internal_blockers),
        external_blockers=tuple(dict.fromkeys(external_blockers)),
    )


__all__ = [
    "CANONICAL_PIPELINE_DATASET_TYPES",
    "DATA_DOMAIN_DATASET_TYPE",
    "UniversalPaperMarketReadinessReport",
    "assess_universal_paper_market_readiness",
]
