"""Terminally accounted certified-universe discovery.

The prior implementation is preserved in
``operations._comprehensive_market_discovery_v4``. This public module keeps the
same API while requiring a terminal selected-or-excluded disposition for every
instrument in each scheduled certified catalog. Comprehensive consideration does
not require a market lane to manufacture a qualifying investment candidate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from cio import CandidateAssetClass
from operations import _comprehensive_market_discovery_v4 as _base
from operations._comprehensive_market_discovery_v4 import *  # noqa: F401,F403
from operations.provider_preselection_publication_runtime import (
    ProviderPreselectionPublicationError,
    ensure_provider_preselection_publication,
)
from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress


_MANIFEST_ENCODER = json.JSONEncoder(
    allow_nan=False,
    separators=(",", ":"),
    sort_keys=True,
)


class _StreamingManifestFingerprint:
    """Hash lane material without retaining a second complete discovery graph.

    The emitted byte stream is exactly the compact, sorted JSON produced by the
    legacy ``_hash`` helper. This changes only peak memory: fingerprints and all
    governed discovery outputs remain identical for identical inputs.
    """

    __slots__ = ("_digest", "_first_lane", "_policy")

    def __init__(self, *, as_of: datetime, policy: str) -> None:
        self._digest = hashlib.sha256()
        self._first_lane = True
        self._policy = policy
        self._digest.update(b'{"as_of":')
        self._update(as_of.isoformat())
        self._digest.update(
            b',"candidate_count_limit_applied":false,"lanes":['
        )

    def _update(self, value: object) -> None:
        for chunk in _MANIFEST_ENCODER.iterencode(value):
            self._digest.update(chunk.encode("utf-8"))

    def append(self, lane_material: Mapping[str, object]) -> None:
        if not self._first_lane:
            self._digest.update(b",")
        self._first_lane = False
        self._update(lane_material)

    def hexdigest(self) -> str:
        completed = self._digest.copy()
        completed.update(b'],"policy":')
        for chunk in _MANIFEST_ENCODER.iterencode(self._policy):
            completed.update(chunk.encode("utf-8"))
        completed.update(b"}")
        return completed.hexdigest()


def _validate_terminal_lane_accounting(
    *,
    asset_class: CandidateAssetClass,
    catalog_records: Sequence[_base._legacy.DiscoveryCatalogRecord],
    selected: Sequence[_base._legacy.DiscoveredMarketInstrument],
    exclusions: Sequence[tuple[str, str]],
) -> tuple[int, int]:
    """Require a terminal selected-or-excluded disposition for every record.

    A scheduled lane may legitimately produce zero selected instruments when every
    catalog instrument was evaluated and rejected by an unchanged policy gate. A
    genuinely empty catalog, overlapping dispositions, unknown symbols, or any
    unaccounted record remains fail-closed.
    """

    catalog_symbols = {item.symbol for item in catalog_records}
    if not catalog_symbols:
        raise _base._legacy.ComprehensiveMarketDiscoveryError(
            "complete discovery cannot certify an empty requested lane: "
            + asset_class.value
        )

    selected_symbols = {item.catalog.symbol for item in selected}
    excluded_symbols = {
        str(symbol).strip().upper()
        for symbol, reason in exclusions
        if str(symbol).strip() and str(reason).strip()
    }
    unexpected = (selected_symbols | excluded_symbols).difference(catalog_symbols)
    overlap = selected_symbols.intersection(excluded_symbols)
    unaccounted = catalog_symbols.difference(selected_symbols | excluded_symbols)
    if unexpected or overlap or unaccounted:
        details = []
        if unexpected:
            details.append("unexpected=" + ",".join(sorted(unexpected)))
        if overlap:
            details.append("overlap=" + ",".join(sorted(overlap)))
        if unaccounted:
            details.append("unaccounted=" + ",".join(sorted(unaccounted)))
        raise _base._legacy.ComprehensiveMarketDiscoveryError(
            f"{asset_class.value} terminal discovery accounting is incomplete: "
            + "; ".join(details)
        )
    return len(selected_symbols), len(excluded_symbols)


def _has_substantive_provider_factor_authority(
    signals: Mapping[str, _base.CatalogScreeningSignal],
) -> bool:
    return any(
        identifier.startswith("provider-factor:")
        for signal in signals.values()
        for identifier in signal.evidence_identifiers
    )


def _provider_publication_failure_reasons(
    signals: Mapping[str, _base.CatalogScreeningSignal],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                reason
                for signal in signals.values()
                for reason in signal.exclusion_reasons
                if reason.startswith(
                    "provider_enriched_preselection_publication_invalid:"
                )
            }
        )
    )


@dataclass(frozen=True, slots=True)
class ComprehensiveMarketDiscoveryPolicy(_base.ComprehensiveMarketDiscoveryPolicy):
    """Govern complete discovery with terminal instrument accounting."""

    version: str = (
        "comprehensive-liquid-market-discovery.v6-provider-publication-authority"
    )


def discover_comprehensive_markets(
    *,
    as_of: datetime,
    held_symbols: Sequence[str] = (),
    tracked_symbols: Sequence[str] = (),
    excluded_symbols: Sequence[str] = (),
    catalog_probe: _base._legacy.CatalogProbe | None = None,
    market_probe: _base._legacy.MarketProbe | None = None,
    preselection_probe: _base.PreselectionProbe | None = None,
    prior_cutoff_observations: Sequence[_base.CutoffObservation] = (),
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
) -> _base.ComprehensiveMarketDiscoveryResult:
    """Screen complete catalogs and forward every eligible evidence-complete asset.

    Candidate scores determine review order only. They never create a top-N cutoff.
    Every scheduled catalog instrument must finish with a selected or excluded
    disposition, but a lane is not required to force an investment candidate through
    unchanged evidence, liquidity, lifecycle, or market-quality gates.

    The canonical uninjected path builds or reuses the exact-catalog provider-factor
    publication before preselection. A zero-candidate lane can certify only when that
    lane contains substantive provider-factor lineage; systemic publication outages
    remain fail-closed rather than being misclassified as normal asset exclusions.
    """

    timestamp = _base._legacy._aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    record_manual_cio_diagnostic_progress(
        "comprehensive_catalog_discovery",
    )
    catalogs = (
        catalog_probe(timestamp)
        if catalog_probe is not None
        else _base._merge_certified_catalog(
            _base.default_catalog_probe(timestamp, policy=resolved),
            as_of=timestamp,
        )
    )
    record_manual_cio_diagnostic_progress(
        "certified_catalog_merge_complete",
        metrics={
            "catalog_records": sum(
                len(items)
                for items in catalogs.values()
                if isinstance(items, Sequence)
            )
        },
    )
    if not isinstance(catalogs, Mapping):
        raise _base._legacy.ComprehensiveMarketDiscoveryError(
            "catalog probe must return a mapping"
        )
    fixture_preselection = (
        preselection_probe is None
        and (catalog_probe is not None or market_probe is not None)
    )
    canonical_publication_required = (
        catalog_probe is None
        and market_probe is None
        and preselection_probe is None
    )
    if canonical_publication_required:
        try:
            record_manual_cio_diagnostic_progress(
                "provider_preselection_publication",
            )
            ensure_provider_preselection_publication(
                catalogs,
                as_of=timestamp,
                policy=resolved,
            )
            record_manual_cio_diagnostic_progress(
                "provider_preselection_publication_complete",
            )
        except ProviderPreselectionPublicationError as error:
            raise _base._legacy.ComprehensiveMarketDiscoveryError(str(error)) from error

    active_preselection_probe = (
        preselection_probe
        or (
            _base.default_catalog_screening_signals
            if fixture_preselection
            else _base.provider_enriched_catalog_screening_signals
        )
    )
    require_provider_factor_lineage = not fixture_preselection

    held = {str(item).strip().upper() for item in held_symbols if str(item).strip()}
    tracked = {
        str(item).strip().upper() for item in tracked_symbols if str(item).strip()
    }
    excluded = {
        str(item).strip().upper() for item in excluded_symbols if str(item).strip()
    }
    lanes: list[_base.DiscoveryLaneResult] = []
    manifest_fingerprint = _StreamingManifestFingerprint(
        as_of=timestamp,
        policy=resolved.version,
    )

    discovery_lanes = _base._dynamic_discovery_lanes(catalogs)
    for asset_class in discovery_lanes:
        if not _base._lane_is_scheduled(asset_class, timestamp):
            reason = "weekend_market_closed"
            lanes.append(
                _base.DiscoveryLaneResult(
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
            manifest_fingerprint.append(
                {
                    "asset_class": asset_class.value,
                    "scheduled": False,
                    "schedule_reason": reason,
                    "catalog": 0,
                    "deep": 0,
                    "selected": [],
                    "sources": [],
                    "candidate_count_limit_applied": False,
                    "provider_enriched_preselection_required": False,
                    "provider_factor_authority_established": False,
                }
            )
            continue

        raw = catalogs.get(asset_class, ())
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise _base._legacy.ComprehensiveMarketDiscoveryError(
                f"{asset_class.value} catalog must be a sequence"
            )
        catalog_records = _base._legacy._deduplicate(tuple(raw))
        records = []
        catalog_exclusions: list[tuple[str, str]] = []
        for item in catalog_records:
            if item.symbol in excluded:
                catalog_exclusions.append(
                    (item.symbol, "explicit_discovery_exclusion")
                )
                continue
            if (
                item.expiration_at is not None
                and item.expiration_at <= timestamp + timedelta(days=7)
            ):
                catalog_exclusions.append(
                    (item.symbol, "catalog_lifecycle_inside_minimum_window")
                )
                continue
            records.append(item)
        records = tuple(records)
        state_symbols = held | tracked
        continuity = tuple(item for item in records if item.symbol in state_symbols)
        ordinary = tuple(item for item in records if item.symbol not in state_symbols)

        record_manual_cio_diagnostic_progress(
            f"terminal_screening:{asset_class.value}",
            metrics={
                "catalog_records": len(catalog_records),
                "continuity_records": len(continuity),
            },
        )
        signals = active_preselection_probe(ordinary, timestamp, resolved)
        if not isinstance(signals, Mapping):
            raise _base._legacy.ComprehensiveMarketDiscoveryError(
                f"{asset_class.value} preselection probe must return a mapping"
            )
        provider_factor_authority_established = False
        if require_provider_factor_lineage:
            signals = _base.validate_provider_enriched_signals(
                ordinary,
                signals,
                required_factors=resolved.required_provider_preselection_factors,
            )
            provider_factor_authority_established = (
                not ordinary or _has_substantive_provider_factor_authority(signals)
            )
            if not provider_factor_authority_established:
                publication_failures = _provider_publication_failure_reasons(signals)
                detail = (
                    "; " + ", ".join(publication_failures)
                    if publication_failures
                    else ""
                )
                raise _base._legacy.ComprehensiveMarketDiscoveryError(
                    f"{asset_class.value} provider factor authority is unavailable "
                    f"for the complete certified catalog{detail}"
                )

        plan = _base.build_preselection_plan(
            ordinary,
            signals,
            as_of=timestamp,
            capacity=max(1, len(ordinary)),
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
        deep_records = tuple(dict.fromkeys((*continuity, *nominated)))
        record_manual_cio_diagnostic_progress(
            f"deep_market_evidence:{asset_class.value}",
            metrics={"decision_eligible_records": len(deep_records)},
        )
        features = (market_probe or _base._legacy.default_market_probe)(
            deep_records, timestamp, resolved
        )
        record_manual_cio_diagnostic_progress(
            f"deep_market_evidence_complete:{asset_class.value}",
            metrics={"evidence_complete_records": len(features)},
        )

        selected: list[_base._legacy.DiscoveredMarketInstrument] = []
        exclusions = [*catalog_exclusions, *plan.exclusions]
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
                _base._legacy.DiscoveredMarketInstrument(
                    catalog=record,
                    features=item_features,
                    retained_for_state=record.symbol in state_symbols,
                )
            )

        selected.sort(
            key=lambda item: (item.score, item.catalog.symbol), reverse=True
        )
        final = tuple(selected)

        current_prices = {
            symbol: item_features.price for symbol, item_features in features.items()
        }
        for symbol, signal in signals.items():
            if signal.indicative_price is not None:
                current_prices.setdefault(symbol, signal.indicative_price)
        observations = _base.build_cutoff_observations(
            plan,
            asset_class=asset_class.value,
            signals=signals,
            selected_prices=current_prices,
        )
        outcomes = _base.evaluate_cutoff_outcomes(
            prior_cutoff_observations,
            asset_class=asset_class.value,
            current_prices=current_prices,
            as_of=timestamp,
        )
        measured_symbols = tuple(
            dict.fromkeys((*plan.selected_symbols, *plan.shadow_symbols))
        )
        preselection_evidence = tuple(
            (
                symbol,
                tuple(signals[symbol].evidence_identifiers),
            )
            for symbol in measured_symbols
            if symbol in signals
        )
        source_identifiers = tuple(
            dict.fromkeys(item.source_identifier for item in catalog_records)
        )
        terminal_selected_count, terminal_excluded_count = (
            _validate_terminal_lane_accounting(
                asset_class=asset_class,
                catalog_records=catalog_records,
                selected=final,
                exclusions=exclusions,
            )
        )
        record_manual_cio_diagnostic_progress(
            f"terminal_accounting_complete:{asset_class.value}",
            metrics={
                "excluded": terminal_excluded_count,
                "selected": terminal_selected_count,
            },
        )
        lanes.append(
            _base.DiscoveryLaneResult(
                asset_class=asset_class,
                catalog_count=len(catalog_records),
                deep_analyzed_count=len(deep_records),
                selected=final,
                exclusions=tuple(exclusions),
                source_identifiers=source_identifiers,
                continuity_count=len(continuity),
                preselection=plan,
                preselection_evidence=preselection_evidence,
                cutoff_observations=observations,
                cutoff_outcomes=outcomes,
            )
        )
        manifest_fingerprint.append(
            {
                "asset_class": asset_class.value,
                "scheduled": True,
                "schedule_reason": None,
                "catalog": len(catalog_records),
                "screenable": len(records),
                "deep": len(deep_records),
                "continuity": len(continuity),
                "terminal_selected_count": terminal_selected_count,
                "terminal_excluded_count": terminal_excluded_count,
                "terminal_accounting_complete": True,
                "candidate_count_limit_applied": False,
                "provider_enriched_preselection_required": (
                    require_provider_factor_lineage
                ),
                "provider_factor_authority_established": (
                    provider_factor_authority_established
                    if require_provider_factor_lineage
                    else None
                ),
                "preselection": plan.to_dict(),
                "preselection_evidence": {
                    symbol: list(identifiers)
                    for symbol, identifiers in preselection_evidence
                },
                "cutoff_outcomes": [item.to_dict() for item in outcomes],
                "selected": [item.catalog.symbol for item in final],
                "sources": list(source_identifiers),
            }
        )

    fingerprint = manifest_fingerprint.hexdigest()
    record_manual_cio_diagnostic_progress(
        "comprehensive_market_discovery_complete",
        metrics={"scheduled_lanes": sum(1 for lane in lanes if lane.scheduled)},
    )
    return _base.ComprehensiveMarketDiscoveryResult(
        identifier=(
            "comprehensive-market-discovery:"
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}:{fingerprint[:16]}"
        ),
        as_of=timestamp,
        policy_version=resolved.version,
        lanes=tuple(lanes),
        manifest_fingerprint=fingerprint,
    )


def __getattr__(name: str):
    return getattr(_base, name)


__all__ = tuple(
    dict.fromkeys(
        (
            *_base.__all__,
            "ComprehensiveMarketDiscoveryPolicy",
            "discover_comprehensive_markets",
            "_validate_terminal_lane_accounting",
            "ensure_provider_preselection_publication",
        )
    )
)
