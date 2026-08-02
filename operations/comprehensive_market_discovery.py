"""Merit-based comprehensive discovery with a 200-candidate deep-analysis budget.

The original provider/catalog implementation is retained verbatim in the adjacent
legacy module. This module replaces only the pre-committee selection architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping, Sequence

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery_legacy as _legacy
from operations.comprehensive_market_discovery_legacy import *  # noqa: F401,F403
from operations.market_discovery_preselection import (
    CatalogScreeningSignal,
    CutoffObservation,
    CutoffOutcomeEvaluation,
    PreselectionPlan,
    build_cutoff_observations,
    build_preselection_plan,
    default_catalog_screening_signals,
    evaluate_cutoff_outcomes,
)


@dataclass(frozen=True, slots=True)
class ComprehensiveMarketDiscoveryPolicy(_legacy.ComprehensiveMarketDiscoveryPolicy):
    version: str = "comprehensive-liquid-market-discovery.v2-sleeved"
    maximum_deep_candidates_per_lane: int = 200
    preselection_shadow_candidates_per_lane: int = 20
    preselection_freshness_days: int = 3
    preselection_minimum_liquidity_score: float = 0.0

    def __post_init__(self) -> None:
        _legacy.ComprehensiveMarketDiscoveryPolicy.__post_init__(self)
        for name in (
            "preselection_shadow_candidates_per_lane",
            "preselection_freshness_days",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not 0.0 <= float(self.preselection_minimum_liquidity_score) <= 1.0:
            raise ValueError(
                "preselection_minimum_liquidity_score must be between 0 and 1"
            )


@dataclass(frozen=True, slots=True)
class DiscoveryLaneResult(_legacy.DiscoveryLaneResult):
    continuity_count: int = 0
    preselection: PreselectionPlan | None = None
    cutoff_observations: tuple[CutoffObservation, ...] = ()
    cutoff_outcomes: tuple[CutoffOutcomeEvaluation, ...] = ()

    def __post_init__(self) -> None:
        _legacy.DiscoveryLaneResult.__post_init__(self)
        if self.continuity_count < 0 or self.continuity_count > self.deep_analyzed_count:
            raise ValueError("continuity_count is outside the deep-analysis cohort")


@dataclass(frozen=True, slots=True)
class ComprehensiveMarketDiscoveryResult(_legacy.ComprehensiveMarketDiscoveryResult):
    lanes: tuple[DiscoveryLaneResult, ...]

    def to_dict(self):
        payload = _legacy.ComprehensiveMarketDiscoveryResult.to_dict(self)
        for lane_payload, lane in zip(payload["lanes"], self.lanes, strict=True):
            lane_payload.update(
                {
                    "continuity_count": lane.continuity_count,
                    "preselection": (
                        None
                        if lane.preselection is None
                        else lane.preselection.to_dict()
                    ),
                    "cutoff_observations": [
                        item.to_dict() for item in lane.cutoff_observations
                    ],
                    "cutoff_outcomes": [
                        item.to_dict() for item in lane.cutoff_outcomes
                    ],
                }
            )
        return payload


PreselectionProbe = Callable[
    [
        Sequence[_legacy.DiscoveryCatalogRecord],
        datetime,
        ComprehensiveMarketDiscoveryPolicy,
    ],
    Mapping[str, CatalogScreeningSignal],
]


def discover_comprehensive_markets(
    *,
    as_of: datetime,
    held_symbols: Sequence[str] = (),
    tracked_symbols: Sequence[str] = (),
    excluded_symbols: Sequence[str] = (),
    catalog_probe: _legacy.CatalogProbe | None = None,
    market_probe: _legacy.MarketProbe | None = None,
    preselection_probe: PreselectionProbe | None = None,
    prior_cutoff_observations: Sequence[CutoffObservation] = (),
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
) -> ComprehensiveMarketDiscoveryResult:
    """Scan complete catalogs, then nominate 200 merit-balanced candidates per lane."""

    timestamp = _legacy._aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    scheduled_lanes = _legacy.scheduled_discovery_lanes(timestamp)
    catalogs = (catalog_probe or _legacy.default_catalog_probe)(timestamp)
    if not isinstance(catalogs, Mapping):
        raise _legacy.ComprehensiveMarketDiscoveryError(
            "catalog probe must return a mapping"
        )
    held = {str(item).strip().upper() for item in held_symbols if str(item).strip()}
    tracked = {
        str(item).strip().upper() for item in tracked_symbols if str(item).strip()
    }
    excluded = {
        str(item).strip().upper() for item in excluded_symbols if str(item).strip()
    }
    lanes: list[DiscoveryLaneResult] = []
    manifest_material: list[dict[str, object]] = []

    for asset_class in _legacy._DISCOVERY_LANES:
        if asset_class not in scheduled_lanes:
            reason = "weekend_market_closed"
            lanes.append(
                DiscoveryLaneResult(
                    asset_class=asset_class,
                    catalog_count=0,
                    deep_analyzed_count=0,
                    selected=(),
                    exclusions=(("__lane__", reason),),
                    source_identifiers=(),
                    scheduled=False,
                    schedule_reason=reason,
                )
            )
            manifest_material.append(
                {
                    "asset_class": asset_class.value,
                    "scheduled": False,
                    "schedule_reason": reason,
                    "catalog": 0,
                    "deep": 0,
                    "selected": [],
                    "sources": [],
                }
            )
            continue

        raw = catalogs.get(asset_class, ())
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise _legacy.ComprehensiveMarketDiscoveryError(
                f"{asset_class.value} catalog must be a sequence"
            )
        records = tuple(
            item
            for item in _legacy._deduplicate(tuple(raw))
            if item.symbol not in excluded
            and (
                item.expiration_at is None
                or item.expiration_at > timestamp + timedelta(days=7)
            )
        )
        state_symbols = held | tracked
        continuity = tuple(item for item in records if item.symbol in state_symbols)
        ordinary = tuple(item for item in records if item.symbol not in state_symbols)

        signals = (preselection_probe or default_catalog_screening_signals)(
            ordinary, timestamp, resolved
        )
        if not isinstance(signals, Mapping):
            raise _legacy.ComprehensiveMarketDiscoveryError(
                f"{asset_class.value} preselection probe must return a mapping"
            )
        plan = build_preselection_plan(
            ordinary,
            signals,
            as_of=timestamp,
            capacity=resolved.maximum_deep_candidates_per_lane,
            shadow_limit=resolved.preselection_shadow_candidates_per_lane,
            freshness_days=resolved.preselection_freshness_days,
            minimum_liquidity_score=resolved.preselection_minimum_liquidity_score,
        )
        ordinary_by_symbol = {item.symbol: item for item in ordinary}
        nominated = tuple(
            ordinary_by_symbol[symbol]
            for symbol in plan.selected_symbols
            if symbol in ordinary_by_symbol
        )
        # Continuity is additive; it does not consume the 200 opportunity slots.
        deep_records = tuple(dict.fromkeys((*continuity, *nominated)))
        features = (market_probe or _legacy.default_market_probe)(
            deep_records, timestamp, resolved
        )

        selected: list[_legacy.DiscoveredMarketInstrument] = []
        exclusions = list(plan.exclusions)
        for record in deep_records:
            item_features = features.get(record.symbol)
            if item_features is None:
                exclusions.append(
                    (record.symbol, "point_in_time_market_evidence_unavailable")
                )
                continue
            if item_features.price < resolved.minimum_price:
                exclusions.append((record.symbol, "price_below_policy_floor"))
                continue
            if (
                record.asset_class
                not in {
                    CandidateAssetClass.FX,
                    CandidateAssetClass.FIXED_INCOME,
                    CandidateAssetClass.OPTION,
                }
                and item_features.average_daily_dollar_volume
                < resolved.minimum_daily_dollar_volume
            ):
                exclusions.append((record.symbol, "liquidity_below_policy_floor"))
                continue
            selected.append(
                _legacy.DiscoveredMarketInstrument(
                    catalog=record,
                    features=item_features,
                    retained_for_state=record.symbol in state_symbols,
                )
            )

        selected.sort(key=lambda item: (item.score, item.catalog.symbol), reverse=True)
        retained_selected = [item for item in selected if item.retained_for_state]
        ordinary_selected = [item for item in selected if not item.retained_for_state]
        final = tuple(
            dict.fromkeys(
                (
                    *retained_selected,
                    *ordinary_selected[: resolved.selected_limit(asset_class)],
                )
            )
        )

        current_prices = {
            symbol: item_features.price for symbol, item_features in features.items()
        }
        for symbol, signal in signals.items():
            if signal.indicative_price is not None:
                current_prices.setdefault(symbol, signal.indicative_price)
        observations = build_cutoff_observations(
            plan,
            asset_class=asset_class.value,
            signals=signals,
            selected_prices=current_prices,
        )
        outcomes = evaluate_cutoff_outcomes(
            prior_cutoff_observations,
            asset_class=asset_class.value,
            current_prices=current_prices,
            as_of=timestamp,
        )
        source_identifiers = tuple(
            dict.fromkeys(item.catalog.source_identifier for item in final)
        )
        lanes.append(
            DiscoveryLaneResult(
                asset_class=asset_class,
                catalog_count=len(records),
                deep_analyzed_count=len(deep_records),
                selected=final,
                exclusions=tuple(exclusions),
                source_identifiers=source_identifiers,
                continuity_count=len(continuity),
                preselection=plan,
                cutoff_observations=observations,
                cutoff_outcomes=outcomes,
            )
        )
        manifest_material.append(
            {
                "asset_class": asset_class.value,
                "scheduled": True,
                "schedule_reason": None,
                "catalog": len(records),
                "deep": len(deep_records),
                "continuity": len(continuity),
                "preselection": plan.to_dict(),
                "cutoff_outcomes": [item.to_dict() for item in outcomes],
                "selected": [item.catalog.symbol for item in final],
                "sources": list(source_identifiers),
            }
        )

    missing = tuple(
        lane.asset_class.value
        for lane in lanes
        if lane.scheduled and not lane.selected
    )
    if missing:
        raise _legacy.ComprehensiveMarketDiscoveryError(
            "complete discovery cannot certify an empty requested lane: "
            + ", ".join(missing)
        )
    fingerprint = _legacy._hash(
        {
            "as_of": timestamp.isoformat(),
            "policy": resolved.version,
            "lanes": manifest_material,
        }
    )
    return ComprehensiveMarketDiscoveryResult(
        identifier=(
            "comprehensive-market-discovery:"
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}:{fingerprint[:16]}"
        ),
        as_of=timestamp,
        policy_version=resolved.version,
        lanes=tuple(lanes),
        manifest_fingerprint=fingerprint,
    )


__all__ = tuple(
    dict.fromkeys(
        (
            *_legacy.__all__,
            "CatalogScreeningSignal",
            "CutoffObservation",
            "CutoffOutcomeEvaluation",
            "PreselectionPlan",
            "PreselectionProbe",
        )
    )
)
