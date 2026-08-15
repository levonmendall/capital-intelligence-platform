"""Bind exact-release reference manifests from already-qualified lane components.

Release deployment must not recollect slow-changing market reference catalogs merely
because the application SHA changed. This module validates the persistent, release-
independent lane components and binds them into the canonical exact-release reference
manifest without calling any external provider.

Missing, stale, corrupt, configuration-mismatched, or coverage-incomplete components
remain fail-closed. The caller may then selectively refresh only the missing component.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, MutableMapping

from cio import CandidateAssetClass
from operations import reference_readiness as _legacy
from operations.generalized_reference_readiness import (
    _EODHD_REFERENCE_LANES,
    _component_records,
    _lane_config_fingerprint,
    _lane_coverage,
    load_asset_reference_component,
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reference binding timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def bind_reference_manifest_from_components(
    values: MutableMapping[str, str],
    *,
    now: datetime | None = None,
):
    """Bind the current release to fresh persistent components with zero provider calls."""

    from operations import _comprehensive_market_discovery_v4 as discovery

    timestamp = _aware(now or datetime.now(timezone.utc))
    config = discovery._base.load_comprehensive_market_discovery_config()
    discovery._base._reject_evidence_only_eodhd_directories(config)
    active_lanes = discovery._base.scheduled_discovery_lanes(timestamp)
    active_lane_names = tuple(sorted(item.value for item in active_lanes))
    config_fingerprint = _legacy._fingerprint(_legacy._config_material(config))
    roots = _legacy._futures_roots(config)

    requested_directory_lanes = tuple(
        sorted(active_lanes & _EODHD_REFERENCE_LANES, key=lambda item: item.value)
    )
    directory_payloads: list[Mapping[str, object]] = []
    directory_catalogs: dict[str, list[Mapping[str, object]]] = {}
    missing: list[str] = []
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
            missing.append(lane.value)
            continue
        directory_payloads.append(payload)
        directory_catalogs[lane.value] = records

    if missing:
        raise _legacy.ReferenceReadinessError(
            "release-independent reference components are missing or stale: "
            + ", ".join(sorted(missing))
        )

    directory_captured_at = (
        min(
            _legacy._parse_captured_at(item, subject="asset directory component")
            for item in directory_payloads
        )
        if directory_payloads
        else timestamp
    )
    directory_component = _legacy._component_payload(
        component=_legacy._DIRECTORY_COMPONENT,
        captured_at=directory_captured_at,
        config_fingerprint=config_fingerprint,
        active_lanes=active_lane_names,
        coverage=tuple(config.eodhd_exchange_codes),
        catalogs=directory_catalogs,
    )
    _legacy._write_reference_progress(
        values,
        stage="reference_eodhd_directories",
        metrics={
            "configured_exchanges": len(config.eodhd_exchange_codes),
            "catalog_records": sum(len(items) for items in directory_catalogs.values()),
            "reused": 1,
        },
        now=timestamp,
    )

    futures_component = None
    if CandidateAssetClass.FUTURE in active_lanes:
        payload = load_asset_reference_component(
            values,
            asset_class=CandidateAssetClass.FUTURE,
            as_of=timestamp,
            config_fingerprint=_lane_config_fingerprint(config, CandidateAssetClass.FUTURE),
            coverage=_lane_coverage(discovery, config, CandidateAssetClass.FUTURE),
        )
        records = [] if payload is None else _component_records(payload)
        if payload is None or not records:
            raise _legacy.ReferenceReadinessError(
                "release-independent reference component is missing or stale: future"
            )
        _legacy._validate_future_records(records, roots)
        futures_component = _legacy._component_payload(
            component=_legacy._FUTURES_COMPONENT,
            captured_at=_legacy._parse_captured_at(
                payload,
                subject="asset futures component",
            ),
            config_fingerprint=config_fingerprint,
            active_lanes=active_lane_names,
            coverage=roots,
            catalogs={CandidateAssetClass.FUTURE.value: records},
        )
        _legacy._write_reference_progress(
            values,
            stage="reference_futures_contracts",
            metrics={
                "configured_futures_roots": len(roots),
                "catalog_records": len(records),
                "reused": 1,
            },
            now=timestamp,
        )

    return _legacy._bind_manifest(
        values=values,
        timestamp=timestamp,
        release=_legacy._release(values),
        config=config,
        config_fingerprint=config_fingerprint,
        active_lane_names=active_lane_names,
        directory_component=directory_component,
        futures_component=futures_component,
        roots=roots,
    )


__all__ = ["bind_reference_manifest_from_components"]
