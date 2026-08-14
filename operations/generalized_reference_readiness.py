"""Generalize governed persistent reference readiness across executable asset lanes.

The original reference-readiness implementation remains the compatibility boundary used
by the bounded CIO child. This module adds lane-scoped persistent components so a change
in the scheduled discovery cohort cannot invalidate otherwise fresh reference material.
It can rebind those independently qualified components into the legacy exact-release
manifest without changing catalog membership or decision evidence.

The storage API accepts every ``CandidateAssetClass``. Collectors are deliberately only
attached where the production discovery stack has an executable reference source. A
missing collector never fabricates readiness. Prices, bars, liquidity, factors, and other
decision-time evidence are not stored here.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from cio import CandidateAssetClass
from operations import reference_readiness as _legacy


_ASSET_COMPONENT_SCHEMA = "governed-asset-reference-component.v1"
_ASSET_REGISTRY_SCHEMA = "governed-asset-reference-registry.v1"
_CATALOG_SCOPE = "catalog"
_EODHD_REFERENCE_LANES = frozenset(
    {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.REAL_ESTATE,
        CandidateAssetClass.ALTERNATIVE,
        CandidateAssetClass.COMMODITY,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
    }
)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _slug(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return text.strip("-.") or "default"


def _asset_root(values: Mapping[str, str]) -> Path:
    return _legacy._reference_root(values) / "assets"


def asset_reference_component_path(
    values: Mapping[str, str],
    asset_class: CandidateAssetClass,
    *,
    scope: str = _CATALOG_SCOPE,
) -> Path:
    """Return the persistent path for any governed asset-reference component."""

    if not isinstance(asset_class, CandidateAssetClass):
        asset_class = CandidateAssetClass(str(asset_class))
    return _asset_root(values) / asset_class.value / f"{_slug(scope)}-latest-qualified.json"


def _component_material(
    *,
    asset_class: CandidateAssetClass,
    scope: str,
    captured_at: datetime,
    config_fingerprint: str,
    coverage: Sequence[str],
    records: Sequence[Mapping[str, object]],
    metadata: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "schema_version": _ASSET_COMPONENT_SCHEMA,
        "asset_class": asset_class.value,
        "scope": str(scope),
        "captured_at": captured_at.isoformat(),
        "config_fingerprint": str(config_fingerprint),
        "coverage": list(coverage),
        "records": [dict(item) for item in records],
        "metadata": dict(metadata or {}),
        "paper_only": True,
        "real_money_authorized": False,
    }


def store_asset_reference_component(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    captured_at: datetime,
    config_fingerprint: str,
    coverage: Sequence[str],
    records: Sequence[Mapping[str, object]],
    scope: str = _CATALOG_SCOPE,
    metadata: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    """Persist an integrity-bound component for any asset class.

    This function is intentionally provider-neutral. Calling it does not make a market
    executable; it only stores reference records supplied by an already governed
    collector.
    """

    timestamp = _aware(captured_at, field_name="captured_at")
    lane = asset_class if isinstance(asset_class, CandidateAssetClass) else CandidateAssetClass(str(asset_class))
    material = _component_material(
        asset_class=lane,
        scope=scope,
        captured_at=timestamp,
        config_fingerprint=config_fingerprint,
        coverage=tuple(str(item) for item in coverage),
        records=records,
        metadata=metadata,
    )
    payload = {**material, "component_id": _legacy._fingerprint(material)}
    _legacy._write_json(
        asset_reference_component_path(values, lane, scope=scope),
        payload,
    )
    return payload


def load_asset_reference_component(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    as_of: datetime,
    scope: str = _CATALOG_SCOPE,
    config_fingerprint: str | None = None,
    coverage: Sequence[str] | None = None,
) -> Mapping[str, object] | None:
    """Load a fresh, integrity-valid lane component or return ``None`` fail-closed."""

    timestamp = _aware(as_of, field_name="as_of")
    lane = asset_class if isinstance(asset_class, CandidateAssetClass) else CandidateAssetClass(str(asset_class))
    path = asset_reference_component_path(values, lane, scope=scope)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != _ASSET_COMPONENT_SCHEMA:
        return None
    if payload.get("asset_class") != lane.value or payload.get("scope") != str(scope):
        return None
    expected_id = str(payload.get("component_id") or "").strip()
    if not expected_id:
        return None
    material = {key: value for key, value in payload.items() if key != "component_id"}
    if _legacy._fingerprint(material) != expected_id:
        return None
    if config_fingerprint is not None and str(payload.get("config_fingerprint") or "") != str(config_fingerprint):
        return None
    if coverage is not None and tuple(payload.get("coverage") or ()) != tuple(str(item) for item in coverage):
        return None
    try:
        captured_at = _legacy._parse_captured_at(payload, subject="asset reference component")
    except _legacy.ReferenceReadinessError:
        return None
    age = timestamp - captured_at
    if age < timedelta(0) or age > _legacy._max_age(values):
        return None
    records = payload.get("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return None
    if any(not isinstance(item, Mapping) for item in records):
        return None
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    return payload


def _lane_config_fingerprint(config, lane: CandidateAssetClass) -> str:
    if lane in _EODHD_REFERENCE_LANES:
        material: Mapping[str, object] = {
            "asset_class": lane.value,
            "eodhd_exchange_codes": list(config.eodhd_exchange_codes),
            "yahoo_exchange_suffixes": [list(item) for item in config.yahoo_exchange_suffixes],
        }
    elif lane is CandidateAssetClass.FUTURE:
        material = {
            "asset_class": lane.value,
            "futures_roots": [dict(item) for item in config.futures_roots],
        }
    elif lane is CandidateAssetClass.OPTION:
        material = {
            "asset_class": lane.value,
            "option_underlyings": list(config.option_underlyings),
        }
    else:
        material = {"asset_class": lane.value}
    return _legacy._fingerprint(material)


def _lane_coverage(discovery, config, lane: CandidateAssetClass) -> tuple[str, ...]:
    if lane in _EODHD_REFERENCE_LANES:
        return tuple(
            exchange
            for exchange in config.eodhd_exchange_codes
            if lane in discovery._possible_lanes_for_exchange(exchange)
        )
    if lane is CandidateAssetClass.FUTURE:
        return _legacy._futures_roots(config)
    if lane is CandidateAssetClass.OPTION:
        return tuple(str(item).strip().upper() for item in config.option_underlyings if str(item).strip())
    return ()


def _component_records(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = payload.get("records")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _prime_legacy_components(
    *,
    values: Mapping[str, str],
    timestamp: datetime,
    discovery,
    config,
    active_lanes: frozenset[CandidateAssetClass],
) -> None:
    """Rebind fresh lane components into the legacy aggregate compatibility files."""

    active_lane_names = tuple(sorted(item.value for item in active_lanes))
    full_config_fingerprint = _legacy._fingerprint(_legacy._config_material(config))
    requested_directory_lanes = tuple(
        sorted(active_lanes & _EODHD_REFERENCE_LANES, key=lambda item: item.value)
    )
    directory_payloads: list[Mapping[str, object]] = []
    directory_catalogs: dict[str, list[Mapping[str, object]]] = {}
    directory_complete = True
    for lane in requested_directory_lanes:
        payload = load_asset_reference_component(
            values,
            asset_class=lane,
            as_of=timestamp,
            config_fingerprint=_lane_config_fingerprint(config, lane),
            coverage=_lane_coverage(discovery, config, lane),
        )
        records = [] if payload is None else _component_records(payload)
        if payload is None or not records:
            directory_complete = False
            break
        directory_payloads.append(payload)
        directory_catalogs[lane.value] = records
    if directory_complete:
        captured_at = (
            min(
                _legacy._parse_captured_at(item, subject="asset directory component")
                for item in directory_payloads
            )
            if directory_payloads
            else timestamp
        )
        aggregate = _legacy._component_payload(
            component=_legacy._DIRECTORY_COMPONENT,
            captured_at=captured_at,
            config_fingerprint=full_config_fingerprint,
            active_lanes=active_lane_names,
            coverage=tuple(config.eodhd_exchange_codes),
            catalogs=directory_catalogs,
        )
        _legacy._write_json(
            _legacy._component_path(values, _legacy._DIRECTORY_COMPONENT),
            aggregate,
        )

    if CandidateAssetClass.FUTURE in active_lanes:
        lane = CandidateAssetClass.FUTURE
        payload = load_asset_reference_component(
            values,
            asset_class=lane,
            as_of=timestamp,
            config_fingerprint=_lane_config_fingerprint(config, lane),
            coverage=_lane_coverage(discovery, config, lane),
        )
        records = [] if payload is None else _component_records(payload)
        if payload is not None and records:
            aggregate = _legacy._component_payload(
                component=_legacy._FUTURES_COMPONENT,
                captured_at=_legacy._parse_captured_at(payload, subject="asset futures component"),
                config_fingerprint=full_config_fingerprint,
                active_lanes=active_lane_names,
                coverage=_legacy._futures_roots(config),
                catalogs={CandidateAssetClass.FUTURE.value: records},
            )
            _legacy._write_json(
                _legacy._component_path(values, _legacy._FUTURES_COMPONENT),
                aggregate,
            )


def _capture_manifest_components(
    *,
    values: Mapping[str, str],
    manifest: _legacy.ReferenceReadinessManifest,
    discovery,
    config,
) -> None:
    try:
        payload = json.loads(manifest.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, Mapping):
        return
    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, Mapping):
        return
    try:
        captured_at = _legacy._parse_captured_at(payload, subject="bound reference manifest")
    except _legacy.ReferenceReadinessError:
        return
    for raw_lane, raw_records in catalogs.items():
        try:
            lane = CandidateAssetClass(str(raw_lane))
        except ValueError:
            continue
        if lane not in _EODHD_REFERENCE_LANES and lane is not CandidateAssetClass.FUTURE:
            continue
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            continue
        records = [item for item in raw_records if isinstance(item, Mapping)]
        if not records or len(records) != len(raw_records):
            continue
        store_asset_reference_component(
            values,
            asset_class=lane,
            captured_at=captured_at,
            config_fingerprint=_lane_config_fingerprint(config, lane),
            coverage=_lane_coverage(discovery, config, lane),
            records=records,
            metadata={"collector": "eodhd_directory" if lane in _EODHD_REFERENCE_LANES else "futures_contracts"},
        )


def _write_asset_registry(
    *,
    values: Mapping[str, str],
    timestamp: datetime,
    discovery,
    config,
    option_ready_underlyings: int,
) -> None:
    lanes: dict[str, object] = {}
    for lane in CandidateAssetClass:
        collector = "runtime_only"
        ready = False
        if lane in _EODHD_REFERENCE_LANES or lane is CandidateAssetClass.FUTURE:
            collector = "eodhd_directory" if lane in _EODHD_REFERENCE_LANES else "futures_contracts"
            ready = load_asset_reference_component(
                values,
                asset_class=lane,
                as_of=timestamp,
                config_fingerprint=_lane_config_fingerprint(config, lane),
                coverage=_lane_coverage(discovery, config, lane),
            ) is not None
        elif lane is CandidateAssetClass.OPTION:
            collector = "alpaca_option_definitions"
            ready = bool(config.option_underlyings) and option_ready_underlyings >= len(config.option_underlyings)
        lanes[lane.value] = {
            "persistent_storage_supported": True,
            "collector": collector,
            "ready": ready,
        }
    material: dict[str, object] = {
        "schema_version": _ASSET_REGISTRY_SCHEMA,
        "updated_at": timestamp.isoformat(),
        "lanes": lanes,
        "paper_only": True,
        "real_money_authorized": False,
    }
    payload = {**material, "registry_id": _legacy._fingerprint(material)}
    _legacy._write_json(_asset_root(values) / "registry.json", payload)


def prepare_reference_readiness(
    values: MutableMapping[str, str],
    *,
    now: datetime | None = None,
    config=None,
    policy=None,
    eodhd_provider=None,
    massive_futures_provider=None,
    force_refresh: bool = False,
) -> _legacy.ReferenceReadinessManifest:
    """Prepare lane-scoped persistent readiness, then bind the canonical manifest."""

    from operations import _comprehensive_market_discovery_v4 as discovery

    timestamp = _aware(now or datetime.now(timezone.utc), field_name="now")
    resolved_config = config or discovery._base.load_comprehensive_market_discovery_config()
    discovery._base._reject_evidence_only_eodhd_directories(resolved_config)
    resolved_policy = policy or discovery.ComprehensiveMarketDiscoveryPolicy()
    active_lanes = discovery._base.scheduled_discovery_lanes(timestamp)

    if not force_refresh:
        _prime_legacy_components(
            values=values,
            timestamp=timestamp,
            discovery=discovery,
            config=resolved_config,
            active_lanes=active_lanes,
        )

    option_ready_underlyings = 0
    if CandidateAssetClass.OPTION in active_lanes:
        try:
            from operations.persistent_option_reference import prewarm_option_reference_definitions

            option_stats = prewarm_option_reference_definitions(
                values,
                as_of=timestamp,
                config=resolved_config,
                policy=resolved_policy,
                force_refresh=force_refresh,
            )
            option_ready_underlyings = int(option_stats.get("ready_underlyings", 0))
        except (OSError, TypeError, ValueError, RuntimeError):
            # Persistent option definitions are an optimization layer. The unchanged
            # exact-epoch Alpaca -> Tradier -> Massive router remains authoritative and
            # fail-closed when the reusable definition layer cannot be prepared.
            option_ready_underlyings = 0

    manifest = _legacy.prepare_reference_readiness(
        values,
        now=timestamp,
        config=resolved_config,
        policy=resolved_policy,
        eodhd_provider=eodhd_provider,
        massive_futures_provider=massive_futures_provider,
        force_refresh=force_refresh,
    )
    _capture_manifest_components(
        values=values,
        manifest=manifest,
        discovery=discovery,
        config=resolved_config,
    )
    _write_asset_registry(
        values=values,
        timestamp=timestamp,
        discovery=discovery,
        config=resolved_config,
        option_ready_underlyings=option_ready_underlyings,
    )
    return manifest


__all__ = [
    "asset_reference_component_path",
    "load_asset_reference_component",
    "prepare_reference_readiness",
    "store_asset_reference_component",
]
