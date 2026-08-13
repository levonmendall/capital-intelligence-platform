"""Freeze and reuse slow-changing market reference data before a bounded CIO cycle.

Release certification must spend its bounded CIO budget on current evidence, specialist
analysis, CIO qualification, construction, and paper implementation rather than waiting
for exchange/security-master APIs. Reference catalogs are checkpointed by component on
persistent storage, validated for freshness/configuration/integrity, and rebound to the
exact release before the bounded CIO process starts.

The reference layer has no investment, ranking, sizing, construction, execution, or
real-money authority. Missing, stale, release-mismatched, configuration-mismatched,
incomplete, or corrupted reference material remains fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from cio import CandidateAssetClass
from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
)

_SCHEMA_VERSION = "governed-reference-readiness.v2"
_COMPONENT_SCHEMA_VERSION = "governed-reference-component.v1"
_PROGRESS_SCHEMA_VERSION = "governed-reference-progress.v1"
_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_DEFAULT_MAX_AGE_MINUTES = 120.0
_DIRECTORY_COMPONENT = "eodhd_directories"
_FUTURES_COMPONENT = "futures_contracts"


class ReferenceReadinessError(RuntimeError):
    """Raised when the governed point-in-time reference manifest is unavailable."""


@dataclass(frozen=True, slots=True)
class ReferenceReadinessManifest:
    manifest_id: str
    release: str
    captured_at: datetime
    config_fingerprint: str
    eodhd_exchanges: tuple[str, ...]
    futures_roots: tuple[str, ...]
    catalog_counts: tuple[tuple[str, int], ...]
    path: Path


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _safe_release(release: str) -> str:
    return "".join(
        character for character in release if character.isalnum() or character in {"-", "_"}
    ) or "unknown"


def _reference_root(values: Mapping[str, str]) -> Path:
    data_root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return data_root / "reference_readiness"


def _manifest_path(values: Mapping[str, str], release: str) -> Path:
    configured = values.get(_MANIFEST_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return _reference_root(values) / f"instrument-master-{_safe_release(release)}.json"


def _component_path(values: Mapping[str, str], component: str) -> Path:
    if component not in {_DIRECTORY_COMPONENT, _FUTURES_COMPONENT}:
        raise ValueError("unsupported reference component")
    return _reference_root(values) / f"{component}-latest-qualified.json"


def _progress_path(values: Mapping[str, str], release: str | None = None) -> Path:
    resolved_release = _release(values) if release is None else release
    return _reference_root(values) / f"progress-{_safe_release(resolved_release)}.json"


def _config_material(config) -> dict[str, object]:
    return {
        "eodhd_exchange_codes": list(config.eodhd_exchange_codes),
        "futures_roots": [dict(item) for item in config.futures_roots],
        "option_underlyings": list(config.option_underlyings),
        "yahoo_exchange_suffixes": [list(item) for item in config.yahoo_exchange_suffixes],
    }


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_payload(record) -> dict[str, object]:
    return {
        "symbol": record.symbol,
        "provider_symbol": record.provider_symbol,
        "name": record.name,
        "asset_class": record.asset_class.value,
        "economic_exposure": record.economic_exposure,
        "venue": record.venue,
        "country_code": record.country_code,
        "currency": record.currency,
        "settlement_currency": record.settlement_currency,
        "instrument_type": record.instrument_type,
        "provider_kind": record.provider_kind,
        "source_identifier": record.source_identifier,
        "instrument_identifier": record.instrument_identifier,
        "contract_multiplier": record.contract_multiplier,
        "quote_spread_bps": record.quote_spread_bps,
        "expiration_at": (
            None
            if record.expiration_at is None
            else record.expiration_at.astimezone(timezone.utc).isoformat()
        ),
        "underlying_symbol": record.underlying_symbol,
        "strike": record.strike,
        "option_right": record.option_right,
        "provider_dataset": record.provider_dataset,
        "provider_stype_in": record.provider_stype_in,
        "provider_instrument_id": record.provider_instrument_id,
    }


def _record_from_payload(payload: Mapping[str, object], record_type):
    expiration = payload.get("expiration_at")
    expiration_at = None
    if expiration not in (None, ""):
        try:
            expiration_at = datetime.fromisoformat(str(expiration).replace("Z", "+00:00"))
        except ValueError as error:
            raise ReferenceReadinessError(
                "reference manifest contains an invalid expiration timestamp"
            ) from error
    try:
        return record_type(
            symbol=str(payload["symbol"]),
            provider_symbol=str(payload["provider_symbol"]),
            name=str(payload["name"]),
            asset_class=CandidateAssetClass(str(payload["asset_class"])),
            economic_exposure=str(payload["economic_exposure"]),
            venue=str(payload["venue"]),
            country_code=str(payload["country_code"]),
            currency=str(payload["currency"]),
            settlement_currency=str(payload["settlement_currency"]),
            instrument_type=str(payload["instrument_type"]),
            provider_kind=str(payload["provider_kind"]),
            source_identifier=str(payload["source_identifier"]),
            instrument_identifier=(
                None
                if payload.get("instrument_identifier") in (None, "")
                else str(payload.get("instrument_identifier"))
            ),
            contract_multiplier=float(payload.get("contract_multiplier", 1.0)),
            quote_spread_bps=float(payload.get("quote_spread_bps", 5.0)),
            expiration_at=expiration_at,
            underlying_symbol=(
                None
                if payload.get("underlying_symbol") in (None, "")
                else str(payload.get("underlying_symbol"))
            ),
            strike=(
                None
                if payload.get("strike") is None
                else float(payload.get("strike"))
            ),
            option_right=(
                None
                if payload.get("option_right") in (None, "")
                else str(payload.get("option_right"))
            ),
            provider_dataset=(
                None
                if payload.get("provider_dataset") in (None, "")
                else str(payload.get("provider_dataset"))
            ),
            provider_stype_in=(
                None
                if payload.get("provider_stype_in") in (None, "")
                else str(payload.get("provider_stype_in"))
            ),
            provider_instrument_id=(
                None
                if payload.get("provider_instrument_id") is None
                else int(payload.get("provider_instrument_id"))
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceReadinessError(
            "reference manifest contains an invalid catalog record"
        ) from error


def _max_age(values: Mapping[str, str]) -> timedelta:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_MAX_AGE_MINUTES", ""
    ).strip()
    if not raw:
        minutes = _DEFAULT_MAX_AGE_MINUTES
    else:
        try:
            minutes = float(raw)
        except ValueError as error:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_MAX_AGE_MINUTES must be numeric"
            ) from error
    if minutes <= 0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_MAX_AGE_MINUTES must be positive"
        )
    return timedelta(minutes=minutes)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_manifest(path: Path, payload: Mapping[str, object]) -> None:
    _write_json(path, payload)


def _write_reference_progress(
    values: Mapping[str, str],
    *,
    stage: str,
    metrics: Mapping[str, int] | None = None,
    now: datetime | None = None,
) -> None:
    allowed = {
        "reference_readiness",
        "reference_eodhd_directories",
        "reference_futures_contracts",
        "reference_manifest_ready",
    }
    if stage not in allowed:
        raise ValueError("reference progress stage is invalid")
    normalized: dict[str, int] = {}
    for raw_name, raw_value in sorted((metrics or {}).items()):
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("reference progress metric name is invalid")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
            raise ValueError("reference progress metrics must be nonnegative integers")
        normalized[raw_name.strip()] = raw_value
    timestamp = _aware(now or datetime.now(timezone.utc), field_name="now")
    payload: dict[str, object] = {
        "schema_version": _PROGRESS_SCHEMA_VERSION,
        "release": _release(values),
        "stage": stage,
        "progress_metrics": normalized,
        "updated_at": timestamp.isoformat(),
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }
    payload["progress_id"] = _fingerprint(payload)
    _write_json(_progress_path(values), payload)


def load_reference_readiness_progress(
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object] | None:
    """Load credential-safe pre-CIO reference progress for the active release."""

    resolved = os.environ if values is None else values
    path = _progress_path(resolved)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != _PROGRESS_SCHEMA_VERSION:
        return None
    if str(payload.get("release") or "").strip() != _release(resolved):
        return None
    expected = str(payload.get("progress_id") or "").strip()
    if not expected:
        return None
    material = {key: value for key, value in payload.items() if key != "progress_id"}
    if _fingerprint(material) != expected:
        return None
    return payload


def _component_material(
    *,
    component: str,
    captured_at: datetime,
    config_fingerprint: str,
    active_lanes: Sequence[str],
    coverage: Sequence[str],
    catalogs: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    return {
        "schema_version": _COMPONENT_SCHEMA_VERSION,
        "component": component,
        "captured_at": captured_at.isoformat(),
        "config_fingerprint": config_fingerprint,
        "active_lanes": list(active_lanes),
        "coverage": list(coverage),
        "catalogs": {name: list(records) for name, records in catalogs.items()},
        "paper_only": True,
        "real_money_authorized": False,
    }


def _component_payload(**kwargs) -> dict[str, object]:
    material = _component_material(**kwargs)
    return {**material, "component_id": _fingerprint(material)}


def _parse_captured_at(payload: Mapping[str, object], *, subject: str) -> datetime:
    try:
        captured = datetime.fromisoformat(
            str(payload.get("captured_at") or "").replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ReferenceReadinessError(f"{subject} captured_at is invalid") from error
    return _aware(captured, field_name=f"{subject} captured_at")


def _validated_component(
    *,
    path: Path,
    component: str,
    timestamp: datetime,
    values: Mapping[str, str],
    config_fingerprint: str,
    active_lanes: Sequence[str],
    coverage: Sequence[str],
) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != _COMPONENT_SCHEMA_VERSION:
        return None
    if payload.get("component") != component:
        return None
    expected_id = str(payload.get("component_id") or "").strip()
    if not expected_id:
        return None
    material = {key: value for key, value in payload.items() if key != "component_id"}
    if _fingerprint(material) != expected_id:
        return None
    if str(payload.get("config_fingerprint") or "") != config_fingerprint:
        return None
    if tuple(payload.get("active_lanes") or ()) != tuple(active_lanes):
        return None
    if tuple(payload.get("coverage") or ()) != tuple(coverage):
        return None
    try:
        captured_at = _parse_captured_at(payload, subject="reference component")
    except ReferenceReadinessError:
        return None
    age = timestamp - captured_at
    if age < timedelta(0) or age > _max_age(values):
        return None
    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, Mapping):
        return None
    return payload


def _serial_catalogs(catalogs) -> dict[str, list[dict[str, object]]]:
    return {
        asset_class.value: [_record_payload(item) for item in records]
        for asset_class, records in sorted(catalogs.items(), key=lambda item: item[0].value)
    }


def _component_catalogs(payload: Mapping[str, object]) -> dict[str, list[Mapping[str, object]]]:
    raw = payload.get("catalogs")
    if not isinstance(raw, Mapping):
        raise ReferenceReadinessError("reference component catalogs are missing")
    result: dict[str, list[Mapping[str, object]]] = {}
    for raw_lane, raw_records in raw.items():
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            raise ReferenceReadinessError("reference component catalog lane must be a sequence")
        records: list[Mapping[str, object]] = []
        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                raise ReferenceReadinessError("reference component record must be an object")
            records.append(raw_record)
        result[str(raw_lane)] = records
    return result


def _futures_roots(config) -> tuple[str, ...]:
    return tuple(
        str(item.get("root", "")).strip().upper()
        for item in config.futures_roots
        if str(item.get("root", "")).strip()
    )


def _validate_future_records(
    records: Sequence[Mapping[str, object]],
    roots: Sequence[str],
) -> None:
    symbols = tuple(str(item.get("symbol") or "").strip().upper() for item in records)
    missing = tuple(root for root in roots if not any(symbol.startswith(root) for symbol in symbols))
    if missing:
        raise ReferenceReadinessError(
            "reference futures catalog is incomplete for configured roots: " + ", ".join(missing)
        )


def _collect_directory_component(
    *,
    discovery,
    timestamp: datetime,
    values: Mapping[str, str],
    config,
    policy,
    provider,
    active_lanes,
    active_lane_names: Sequence[str],
    config_fingerprint: str,
) -> Mapping[str, object]:
    _write_reference_progress(
        values,
        stage="reference_eodhd_directories",
        metrics={"configured_exchanges": len(config.eodhd_exchange_codes), "reused": 0},
        now=timestamp,
    )
    catalogs = {
        key: list(value)
        for key, value in discovery._catalog_from_eodhd(
            as_of=timestamp,
            config=config,
            provider=provider,
            policy=policy,
            requested_asset_classes=active_lanes,
        ).items()
    }
    serial = _serial_catalogs(catalogs)
    payload = _component_payload(
        component=_DIRECTORY_COMPONENT,
        captured_at=timestamp,
        config_fingerprint=config_fingerprint,
        active_lanes=active_lane_names,
        coverage=tuple(config.eodhd_exchange_codes),
        catalogs=serial,
    )
    _write_json(_component_path(values, _DIRECTORY_COMPONENT), payload)
    _write_reference_progress(
        values,
        stage="reference_eodhd_directories",
        metrics={
            "configured_exchanges": len(config.eodhd_exchange_codes),
            "catalog_records": sum(len(items) for items in serial.values()),
            "reused": 0,
        },
    )
    return payload


def _collect_futures_component(
    *,
    discovery,
    timestamp: datetime,
    values: Mapping[str, str],
    config,
    massive_futures_provider,
    active_lane_names: Sequence[str],
    config_fingerprint: str,
    roots: Sequence[str],
) -> Mapping[str, object]:
    _write_reference_progress(
        values,
        stage="reference_futures_contracts",
        metrics={"configured_futures_roots": len(roots), "reused": 0},
    )
    records = list(
        discovery._base._legacy._futures_catalog(
            as_of=timestamp,
            config=config,
            massive_futures_provider=massive_futures_provider,
        )
    )
    serial_records = [_record_payload(item) for item in records]
    _validate_future_records(serial_records, roots)
    payload = _component_payload(
        component=_FUTURES_COMPONENT,
        captured_at=timestamp,
        config_fingerprint=config_fingerprint,
        active_lanes=active_lane_names,
        coverage=roots,
        catalogs={CandidateAssetClass.FUTURE.value: serial_records},
    )
    _write_json(_component_path(values, _FUTURES_COMPONENT), payload)
    _write_reference_progress(
        values,
        stage="reference_futures_contracts",
        metrics={
            "configured_futures_roots": len(roots),
            "catalog_records": len(serial_records),
            "reused": 0,
        },
    )
    return payload


def _bind_manifest(
    *,
    values: MutableMapping[str, str],
    timestamp: datetime,
    release: str,
    config,
    config_fingerprint: str,
    active_lane_names: Sequence[str],
    directory_component: Mapping[str, object],
    futures_component: Mapping[str, object] | None,
    roots: Sequence[str],
) -> ReferenceReadinessManifest:
    serial_catalogs = _component_catalogs(directory_component)
    component_times = [
        _parse_captured_at(directory_component, subject="directory component")
    ]
    component_ids = {
        _DIRECTORY_COMPONENT: str(directory_component.get("component_id") or "")
    }
    if futures_component is not None:
        future_catalogs = _component_catalogs(futures_component)
        future_records = future_catalogs.get(CandidateAssetClass.FUTURE.value, [])
        _validate_future_records(future_records, roots)
        serial_catalogs[CandidateAssetClass.FUTURE.value] = list(future_records)
        component_times.append(
            _parse_captured_at(futures_component, subject="futures component")
        )
        component_ids[_FUTURES_COMPONENT] = str(
            futures_component.get("component_id") or ""
        )
    captured_at = min(component_times)
    if timestamp - captured_at > _max_age(values):
        raise ReferenceReadinessError("reference components are stale before manifest binding")
    material: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "release": release,
        "captured_at": captured_at.isoformat(),
        "bound_at": timestamp.isoformat(),
        "config_fingerprint": config_fingerprint,
        "eodhd_exchanges": list(config.eodhd_exchange_codes),
        "futures_roots": list(roots),
        "active_lanes": list(active_lane_names),
        "component_ids": component_ids,
        "component_captured_at": [item.isoformat() for item in sorted(component_times)],
        "catalogs": serial_catalogs,
        "paper_only": True,
        "real_money_authorized": False,
    }
    manifest_id = _fingerprint(material)
    payload = {**material, "manifest_id": manifest_id}
    path = _manifest_path(values, release)
    _write_manifest(path, payload)
    values[_MANIFEST_PATH_ENV] = str(path)
    values[_MANIFEST_ID_ENV] = manifest_id
    counts = tuple(sorted((name, len(records)) for name, records in serial_catalogs.items()))
    _write_reference_progress(
        values,
        stage="reference_manifest_ready",
        metrics={
            "catalog_records": sum(count for _, count in counts),
            "configured_exchanges": len(config.eodhd_exchange_codes),
            "configured_futures_roots": len(roots),
        },
    )
    return ReferenceReadinessManifest(
        manifest_id=manifest_id,
        release=release,
        captured_at=captured_at,
        config_fingerprint=config_fingerprint,
        eodhd_exchanges=tuple(config.eodhd_exchange_codes),
        futures_roots=tuple(roots),
        catalog_counts=counts,
        path=path,
    )


def prepare_reference_readiness(
    values: MutableMapping[str, str],
    *,
    now: datetime | None = None,
    config=None,
    policy=None,
    eodhd_provider=None,
    massive_futures_provider=None,
    force_refresh: bool = False,
) -> ReferenceReadinessManifest:
    """Reuse qualified component checkpoints or refresh only missing/stale components."""

    from operations import _comprehensive_market_discovery_v4 as discovery

    timestamp = _aware(now or datetime.now(timezone.utc), field_name="now")
    release = _release(values)
    resolved_config = config or discovery._base.load_comprehensive_market_discovery_config()
    discovery._base._reject_evidence_only_eodhd_directories(resolved_config)
    resolved_policy = policy or discovery.ComprehensiveMarketDiscoveryPolicy()
    active_lanes = discovery._base.scheduled_discovery_lanes(timestamp)
    active_lane_names = tuple(sorted(item.value for item in active_lanes))
    config_fingerprint = _fingerprint(_config_material(resolved_config))
    roots = _futures_roots(resolved_config)

    _write_reference_progress(
        values,
        stage="reference_readiness",
        metrics={
            "configured_exchanges": len(resolved_config.eodhd_exchange_codes),
            "configured_futures_roots": len(roots),
        },
        now=timestamp,
    )

    directory_component = None
    if not force_refresh:
        directory_component = _validated_component(
            path=_component_path(values, _DIRECTORY_COMPONENT),
            component=_DIRECTORY_COMPONENT,
            timestamp=timestamp,
            values=values,
            config_fingerprint=config_fingerprint,
            active_lanes=active_lane_names,
            coverage=tuple(resolved_config.eodhd_exchange_codes),
        )
    if directory_component is None:
        provider = eodhd_provider or discovery._base._legacy.build_eodhd_provider()
        try:
            directory_component = _collect_directory_component(
                discovery=discovery,
                timestamp=timestamp,
                values=values,
                config=resolved_config,
                policy=resolved_policy,
                provider=provider,
                active_lanes=active_lanes,
                active_lane_names=active_lane_names,
                config_fingerprint=config_fingerprint,
            )
        except Exception as error:
            raise ReferenceReadinessError(
                "reference directory collection failed before the CIO cycle: "
                f"{type(error).__name__}: {error}"
            ) from error
    else:
        directory_catalogs = _component_catalogs(directory_component)
        _write_reference_progress(
            values,
            stage="reference_eodhd_directories",
            metrics={
                "configured_exchanges": len(resolved_config.eodhd_exchange_codes),
                "catalog_records": sum(len(items) for items in directory_catalogs.values()),
                "reused": 1,
            },
        )

    futures_component = None
    if CandidateAssetClass.FUTURE in active_lanes:
        if not force_refresh:
            futures_component = _validated_component(
                path=_component_path(values, _FUTURES_COMPONENT),
                component=_FUTURES_COMPONENT,
                timestamp=timestamp,
                values=values,
                config_fingerprint=config_fingerprint,
                active_lanes=active_lane_names,
                coverage=roots,
            )
            if futures_component is not None:
                try:
                    future_records = _component_catalogs(futures_component).get(
                        CandidateAssetClass.FUTURE.value, []
                    )
                    _validate_future_records(future_records, roots)
                except ReferenceReadinessError:
                    futures_component = None
        if futures_component is None:
            try:
                futures_component = _collect_futures_component(
                    discovery=discovery,
                    timestamp=timestamp,
                    values=values,
                    config=resolved_config,
                    massive_futures_provider=massive_futures_provider,
                    active_lane_names=active_lane_names,
                    config_fingerprint=config_fingerprint,
                    roots=roots,
                )
            except Exception as error:
                raise ReferenceReadinessError(
                    "reference futures collection failed before the CIO cycle: "
                    f"{type(error).__name__}: {error}"
                ) from error
        else:
            future_records = _component_catalogs(futures_component).get(
                CandidateAssetClass.FUTURE.value, []
            )
            _write_reference_progress(
                values,
                stage="reference_futures_contracts",
                metrics={
                    "configured_futures_roots": len(roots),
                    "catalog_records": len(future_records),
                    "reused": 1,
                },
            )

    return _bind_manifest(
        values=values,
        timestamp=timestamp,
        release=release,
        config=resolved_config,
        config_fingerprint=config_fingerprint,
        active_lane_names=active_lane_names,
        directory_component=directory_component,
        futures_component=futures_component,
        roots=roots,
    )


def load_reference_catalogs(
    *,
    as_of: datetime,
    config,
    values: Mapping[str, str] | None = None,
    record_type=None,
) -> Mapping[CandidateAssetClass, tuple[object, ...]] | None:
    """Load the exact pre-CIO reference catalogs when a manifest is explicitly bound."""

    resolved = os.environ if values is None else values
    configured_path = resolved.get(_MANIFEST_PATH_ENV, "").strip()
    if not configured_path:
        return None
    timestamp = _aware(as_of, field_name="as_of")
    path = Path(configured_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReferenceReadinessError(
            "bound reference manifest is unavailable or invalid"
        ) from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise ReferenceReadinessError("bound reference manifest schema is invalid")

    release = _release(resolved)
    if str(payload.get("release") or "").strip() != release:
        raise ReferenceReadinessError("bound reference manifest release does not match")
    expected_id = str(payload.get("manifest_id") or "").strip()
    if not expected_id:
        raise ReferenceReadinessError("bound reference manifest id is missing")
    material = {key: value for key, value in payload.items() if key != "manifest_id"}
    if _fingerprint(material) != expected_id:
        raise ReferenceReadinessError("bound reference manifest integrity check failed")
    configured_id = resolved.get(_MANIFEST_ID_ENV, "").strip()
    if configured_id and configured_id != expected_id:
        raise ReferenceReadinessError("bound reference manifest identity changed")

    captured_at = _parse_captured_at(payload, subject="bound reference manifest")
    age = timestamp - captured_at
    if age < timedelta(0) or age > _max_age(resolved):
        raise ReferenceReadinessError("bound reference manifest is stale for this CIO cutoff")

    if str(payload.get("config_fingerprint") or "") != _fingerprint(_config_material(config)):
        raise ReferenceReadinessError(
            "bound reference manifest configuration does not match the CIO cycle"
        )
    if tuple(payload.get("eodhd_exchanges") or ()) != tuple(config.eodhd_exchange_codes):
        raise ReferenceReadinessError(
            "bound reference manifest exchange coverage does not match configuration"
        )
    expected_roots = _futures_roots(config)
    if tuple(payload.get("futures_roots") or ()) != expected_roots:
        raise ReferenceReadinessError(
            "bound reference manifest futures coverage does not match configuration"
        )

    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, Mapping):
        raise ReferenceReadinessError("bound reference manifest catalogs are missing")
    if CandidateAssetClass.FUTURE.value in catalogs and expected_roots:
        raw_futures = catalogs.get(CandidateAssetClass.FUTURE.value)
        if not isinstance(raw_futures, Sequence) or isinstance(raw_futures, (str, bytes)):
            raise ReferenceReadinessError("bound reference futures catalog must be a sequence")
        future_records = [item for item in raw_futures if isinstance(item, Mapping)]
        if len(future_records) != len(raw_futures):
            raise ReferenceReadinessError("bound reference futures catalog record must be an object")
        _validate_future_records(future_records, expected_roots)

    if record_type is None:
        from operations.comprehensive_market_discovery_legacy import DiscoveryCatalogRecord

        record_type = DiscoveryCatalogRecord

    result: dict[CandidateAssetClass, tuple[object, ...]] = {}
    for raw_lane, raw_records in catalogs.items():
        try:
            asset_class = CandidateAssetClass(str(raw_lane))
        except ValueError as error:
            raise ReferenceReadinessError(
                "bound reference manifest contains an unsupported market lane"
            ) from error
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            raise ReferenceReadinessError(
                "bound reference manifest catalog lane must be a sequence"
            )
        normalized = []
        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                raise ReferenceReadinessError(
                    "bound reference manifest catalog record must be an object"
                )
            normalized.append(_record_from_payload(raw_record, record_type))
        result[asset_class] = tuple(normalized)
    return result


def fail_reference_readiness_request(values: Mapping[str, str], *, detail: str) -> None:
    """Close a release request fail-closed when reference readiness never completes."""

    request = latest_manual_cio_diagnostic(values=values)
    if request is None or request.state in {"completed", "failed"}:
        return
    if request.state == "pending":
        request = claim_manual_cio_diagnostic(values=values)
    if request is None or request.state != "in_progress":
        return
    finish_manual_cio_diagnostic(
        request,
        succeeded=False,
        cycle_key=request.cycle_key,
        snapshot_identifier=request.snapshot_identifier,
        detail="Reference readiness failed before the bounded CIO cycle started; "
        + str(detail),
        values=values,
    )


__all__ = [
    "ReferenceReadinessError",
    "ReferenceReadinessManifest",
    "fail_reference_readiness_request",
    "load_reference_catalogs",
    "load_reference_readiness_progress",
    "prepare_reference_readiness",
]
