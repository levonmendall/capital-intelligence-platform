"""Configured provider for certified Phase-5 forward intelligence and exposure edges.

This adapter is intentionally provider-neutral.  It only materializes an existing
forward engine when a reviewed dataset binding explicitly supplies that engine's
canonical observation contract at the candidate decision timestamp.  Missing
bindings remain unavailable; configured malformed evidence fails closed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetSnapshot, ProviderDatasetType
from intelligence.forward import (
    AssetPolicySensitivity,
    CurrencyExposure,
    CurrencyObservation,
    CurrencyTransmissionEngine,
    MarketTrendEngine,
    MarketTrendObservation,
    MonetaryPolicyObservation,
    MonetaryPolicyTransmissionEngine,
    PolicyMotive,
    PolicyRegime,
    StrategicBusinessEngine,
    StrategicBusinessObservation,
    StructuralThemeEngine,
    StructuralThemeObservation,
    ThemeLink,
    ThemeNodeObservation,
    build_forward_intelligence_bundle,
)
from intelligence.global_opportunity import (
    CanonicalExposureGraph,
    ExposureGraphEdge,
    ExposureGraphNode,
    ExposureNodeKind,
)
from providers.configured_dataset import ConfiguredDatasetProvider


_FORWARD_TYPES = frozenset(
    {
        ProviderDatasetType.FORWARD_BUSINESS,
        ProviderDatasetType.FORWARD_TREND,
        ProviderDatasetType.FORWARD_THEME,
        ProviderDatasetType.FORWARD_MONETARY,
        ProviderDatasetType.FORWARD_CURRENCY,
        ProviderDatasetType.EXPOSURE_GRAPH,
    }
)


def _rows(snapshot: ProviderDatasetSnapshot) -> tuple[Mapping[str, Any], ...]:
    payload = snapshot.payload
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, Mapping))
    for key in ("data", "rows", "observations", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, Mapping))
    return (payload,)


def _strings(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if value is None:
        values: tuple[object, ...] = ()
    elif isinstance(value, (list, tuple)):
        values = tuple(value)
    else:
        raise TypeError(f"{field_name} must be an array")
    result = tuple(str(item).strip() for item in values)
    if any(not item for item in result):
        raise ValueError(f"{field_name} cannot contain empty values")
    if len(result) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} value(s)")
    return tuple(dict.fromkeys(result))


def _evidence(snapshot: ProviderDatasetSnapshot, row: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    values = [f"provider-dataset:{snapshot.provider}:{snapshot.content_hash}"]
    if row is not None:
        values.extend(_strings(row.get("evidence_identifiers"), field_name="evidence_identifiers"))
    return tuple(dict.fromkeys(values))


def _row(snapshot: ProviderDatasetSnapshot) -> Mapping[str, Any]:
    rows = _rows(snapshot)
    if len(rows) != 1:
        raise ValueError(
            f"{snapshot.query.dataset_type.value} must return exactly one candidate observation"
        )
    return rows[0]


class ConfiguredForwardIntelligenceProvider:
    """Materialize the existing five Phase-5 engines from certified observations."""

    def __init__(self, provider: ConfiguredDatasetProvider) -> None:
        if not isinstance(provider, ConfiguredDatasetProvider):
            raise TypeError("provider must be ConfiguredDatasetProvider")
        self.provider = provider
        self.bound_types = frozenset(
            binding.dataset_type
            for binding in provider.settings.bindings
            if binding.dataset_type in _FORWARD_TYPES
        )
        if not self.bound_types:
            raise ValueError("configured provider has no forward-intelligence bindings")

    @property
    def name(self) -> str:
        return f"{self.provider.name}:forward-intelligence"

    def _snapshot(self, dataset_type: ProviderDatasetType, *, symbol: str, as_of):
        if dataset_type not in self.bound_types:
            return None
        return self.provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=dataset_type,
                provider_symbol=str(symbol).upper(),
                as_of=as_of,
                limit=10_000,
            )
        )

    def fetch(self, candidate):
        symbol = candidate.instrument.symbol
        as_of = candidate.as_of
        business = trend = theme = monetary = currency = None

        snapshot = self._snapshot(ProviderDatasetType.FORWARD_BUSINESS, symbol=symbol, as_of=as_of)
        if snapshot is not None:
            row = _row(snapshot)
            business = StrategicBusinessEngine().analyze(
                StrategicBusinessObservation(
                    identifier=str(row.get("identifier") or f"business:{symbol}:{snapshot.content_hash[:16]}"),
                    as_of=as_of,
                    revenue_exposure=float(row["revenue_exposure"]),
                    demand_growth=float(row["demand_growth"]),
                    pricing_power=float(row["pricing_power"]),
                    capacity_adequacy=float(row["capacity_adequacy"]),
                    incremental_margin=float(row["incremental_margin"]),
                    market_share_trend=float(row["market_share_trend"]),
                    capital_allocation_quality=float(row["capital_allocation_quality"]),
                    customer_concentration=float(row["customer_concentration"]),
                    supplier_concentration=float(row["supplier_concentration"]),
                    valuation_priced_in=float(row["valuation_priced_in"]),
                    evidence=_strings(row.get("evidence"), field_name="business evidence", minimum=1),
                    risks=_strings(row.get("risks"), field_name="business risks", minimum=1),
                    evidence_identifiers=_evidence(snapshot, row),
                )
            )

        snapshot = self._snapshot(ProviderDatasetType.FORWARD_TREND, symbol=symbol, as_of=as_of)
        if snapshot is not None:
            row = _row(snapshot)
            trend = MarketTrendEngine().analyze(
                MarketTrendObservation(
                    identifier=str(row.get("identifier") or f"trend:{symbol}:{snapshot.content_hash[:16]}"),
                    as_of=as_of,
                    absolute_trend=float(row["absolute_trend"]),
                    relative_trend=float(row["relative_trend"]),
                    breadth=float(row["breadth"]),
                    earnings_revision_breadth=float(row["earnings_revision_breadth"]),
                    volume_confirmation=float(row["volume_confirmation"]),
                    leadership_concentration=float(row["leadership_concentration"]),
                    crowding=float(row["crowding"]),
                    valuation_expansion_share=float(row["valuation_expansion_share"]),
                    reversal_signal=float(row["reversal_signal"]),
                    evidence=_strings(row.get("evidence"), field_name="trend evidence", minimum=1),
                    evidence_identifiers=_evidence(snapshot, row),
                )
            )

        snapshot = self._snapshot(ProviderDatasetType.FORWARD_THEME, symbol=symbol, as_of=as_of)
        if snapshot is not None:
            row = _row(snapshot)
            nodes = tuple(
                ThemeNodeObservation(
                    name=str(item["name"]),
                    demand_growth=float(item["demand_growth"]),
                    capacity_growth=float(item["capacity_growth"]),
                    utilization=float(item["utilization"]),
                    lead_time_pressure=float(item["lead_time_pressure"]),
                    pricing_power=float(item["pricing_power"]),
                    supplier_concentration=float(item["supplier_concentration"]),
                    substitution_risk=float(item["substitution_risk"]),
                    beneficiary_symbols=_strings(item.get("beneficiary_symbols"), field_name="beneficiary_symbols"),
                    evidence_identifiers=_evidence(snapshot, item),
                )
                for item in row["nodes"]
                if isinstance(item, Mapping)
            )
            links = tuple(
                ThemeLink(
                    source=str(item["source"]),
                    target=str(item["target"]),
                    transmission_strength=float(item["transmission_strength"]),
                    lag_days=int(item["lag_days"]),
                )
                for item in row["links"]
                if isinstance(item, Mapping)
            )
            theme = StructuralThemeEngine().analyze(
                StructuralThemeObservation(
                    identifier=str(row.get("identifier") or f"theme:{symbol}:{snapshot.content_hash[:16]}"),
                    name=str(row["name"]),
                    as_of=as_of,
                    demand_origin=str(row["demand_origin"]),
                    candidate_node=str(row["candidate_node"]),
                    nodes=nodes,
                    links=links,
                    theme_demand_growth=float(row["theme_demand_growth"]),
                    market_pricing_score=float(row["market_pricing_score"]),
                    evidence=_strings(row.get("evidence"), field_name="theme evidence", minimum=1),
                )
            )

        snapshot = self._snapshot(ProviderDatasetType.FORWARD_MONETARY, symbol=symbol, as_of=as_of)
        if snapshot is not None:
            row = _row(snapshot)
            sensitivity = row.get("sensitivity")
            if not isinstance(sensitivity, Mapping):
                raise TypeError("forward monetary observation requires sensitivity object")
            monetary = MonetaryPolicyTransmissionEngine().analyze(
                MonetaryPolicyObservation(
                    identifier=str(row.get("identifier") or f"monetary:{symbol}:{snapshot.content_hash[:16]}"),
                    as_of=as_of,
                    regime=PolicyRegime(str(row["regime"])),
                    motive=PolicyMotive(str(row["motive"])),
                    inflation_trend=float(row["inflation_trend"]),
                    growth_trend=float(row["growth_trend"]),
                    financial_stress=float(row["financial_stress"]),
                    liquidity_impulse=float(row["liquidity_impulse"]),
                    real_yield_change=float(row["real_yield_change"]),
                    credit_spread_change=float(row["credit_spread_change"]),
                    market_pricing_score=float(row["market_pricing_score"]),
                    evidence=_strings(row.get("evidence"), field_name="monetary evidence", minimum=1),
                    evidence_identifiers=_evidence(snapshot, row),
                ),
                AssetPolicySensitivity(
                    liquidity=float(sensitivity["liquidity"]),
                    duration=float(sensitivity["duration"]),
                    credit=float(sensitivity["credit"]),
                    inflation=float(sensitivity["inflation"]),
                    growth=float(sensitivity["growth"]),
                ),
            )

        snapshot = self._snapshot(ProviderDatasetType.FORWARD_CURRENCY, symbol=symbol, as_of=as_of)
        if snapshot is not None:
            row = _row(snapshot)
            exposure = row.get("exposure")
            if not isinstance(exposure, Mapping):
                raise TypeError("forward currency observation requires exposure object")
            currency = CurrencyTransmissionEngine().analyze(
                CurrencyObservation(
                    identifier=str(row.get("identifier") or f"currency:{symbol}:{snapshot.content_hash[:16]}"),
                    as_of=as_of,
                    base_currency=str(row["base_currency"]),
                    reporting_currency=str(row["reporting_currency"]),
                    dollar_strength=float(row["dollar_strength"]),
                    real_yield_differential=float(row["real_yield_differential"]),
                    dollar_funding_stress=float(row["dollar_funding_stress"]),
                    fx_volatility=float(row["fx_volatility"]),
                    commodity_dollar_beta=float(row["commodity_dollar_beta"]),
                    market_pricing_score=float(row["market_pricing_score"]),
                    evidence=_strings(row.get("evidence"), field_name="currency evidence", minimum=1),
                    evidence_identifiers=_evidence(snapshot, row),
                ),
                CurrencyExposure(
                    unhedged_foreign_asset_share=float(exposure["unhedged_foreign_asset_share"]),
                    foreign_revenue_share=float(exposure["foreign_revenue_share"]),
                    usd_revenue_share=float(exposure["usd_revenue_share"]),
                    local_cost_share=float(exposure["local_cost_share"]),
                    usd_debt_share=float(exposure["usd_debt_share"]),
                    commodity_input_share=float(exposure["commodity_input_share"]),
                    commodity_revenue_share=float(exposure["commodity_revenue_share"]),
                    emerging_market_funding_sensitivity=float(exposure["emerging_market_funding_sensitivity"]),
                    hedge_ratio=float(exposure["hedge_ratio"]),
                ),
            )

        if all(item is None for item in (business, trend, theme, monetary, currency)):
            return None
        return build_forward_intelligence_bundle(
            identifier=f"forward:configured:{candidate.identifier}:{as_of.isoformat()}",
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            business=business,
            trend=trend,
            theme=theme,
            monetary=monetary,
            currency=currency,
        )

    def exposure_graph(self, instruments, *, as_of):
        snapshot = self._snapshot(ProviderDatasetType.EXPOSURE_GRAPH, symbol="ALL", as_of=as_of)
        if snapshot is None:
            return CanonicalExposureGraph.from_instruments(instruments, as_of=as_of)
        payload = snapshot.payload
        if not isinstance(payload, Mapping):
            raise TypeError("exposure graph dataset must contain an object")
        nodes = []
        for index, item in enumerate(payload.get("nodes", ())):
            if not isinstance(item, Mapping):
                raise TypeError("exposure graph nodes must be objects")
            nodes.append(
                ExposureGraphNode(
                    identifier=str(item["identifier"]),
                    kind=ExposureNodeKind(str(item["kind"])),
                    label=str(item["label"]),
                    as_of=as_of,
                    evidence_identifiers=_evidence(snapshot, item),
                )
            )
        edges = []
        for index, item in enumerate(payload.get("edges", ())):
            if not isinstance(item, Mapping):
                raise TypeError("exposure graph edges must be objects")
            if item.get("explicit_reviewed") is not True:
                raise ValueError("configured exposure graph edges must be explicitly reviewed")
            edges.append(
                ExposureGraphEdge(
                    identifier=str(item.get("identifier") or f"configured-edge:{index}:{snapshot.content_hash[:16]}"),
                    source_identifier=str(item["source_identifier"]),
                    target_identifier=str(item["target_identifier"]),
                    relationship=str(item["relationship"]),
                    as_of=as_of,
                    confidence=float(item["confidence"]),
                    evidence_identifiers=_evidence(snapshot, item),
                    explicit_reviewed=True,
                )
            )
        return CanonicalExposureGraph.from_instruments(
            instruments,
            as_of=as_of,
            explicit_nodes=tuple(nodes),
            explicit_edges=tuple(edges),
        )


def build_configured_forward_intelligence_provider(
    path: str | Path | None = None,
) -> ConfiguredForwardIntelligenceProvider | None:
    configured_path = str(
        path
        or os.getenv("CAPITAL_INTELLIGENCE_FORWARD_INTELLIGENCE_DATASET_BINDING", "")
    ).strip()
    if not configured_path:
        return None
    return ConfiguredForwardIntelligenceProvider(
        ConfiguredDatasetProvider.from_path(configured_path)
    )


__all__ = [
    "ConfiguredForwardIntelligenceProvider",
    "build_configured_forward_intelligence_provider",
]
