"""Freeze slow-changing market reference data before a bounded CIO cycle.

Release certification must spend its bounded CIO budget on current evidence, specialist
analysis, CIO qualification, construction, and paper implementation rather than waiting
for exchange/security-master APIs. This module performs the slow-changing catalog work
before the bounded diagnostic process starts, persists the exact point-in-time records,
and makes that frozen manifest available to comprehensive discovery.

The manifest has no investment, ranking, sizing, construction, execution, or real-money
authority. Missing, stale, release-mismatched, configuration-mismatched, or incomplete
reference material remains fail-closed.
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

_SCHEMA_VERSION = "governed-reference-readiness.v1"
_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_DEFAULT_MAX_AGE_MINUTES = 120.0


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


def _manifest_path(values: Mapping[str, str], release: str) -> Path:
    configured = values.get(_MANIFEST_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    data_root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    safe_release = "".join(
        character for character in release if character.isalnum() or character in {"-", "_"}
    ) or "unknown"
    return data_root / "reference_readiness" / f"instrument-master-{safe_release}.json"


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
            None if record.expiration_at is None else record.expiration_at.astimezone(timezone.utc).isoformat()
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
            instrument_identifier=(None if payload.get("instrument_identifier") in (None, "") else str(payload.get("instrument_identifier"))),
            contract_multiplier=float(payload.get("contract_multiplier", 1.0)),
            quote_spread_bps=float(payload.get("quote_spread_bps", 5.0)),
            expiration_at=expiration_at,
            underlying_symbol=(None if payload.get("underlying_symbol") in (None, "") else str(payload.get("underlying_symbol"))),
            strike=(None if payload.get("strike") is None else float(payload.get("strike"))),
            option_right=(None if payload.get("option_right") in (None, "") else str(payload.get("option_right"))),
            provider_dataset=(None if payload.get("provider_dataset") in (None, "") else str(payload.get("provider_dataset"))),
            provider_stype_in=(None if payload.get("provider_stype_in") in (None, "") else str(payload.get("provider_stype_in"))),
            provider_instrument_id=(None if payload.get("provider_instrument_id") is None else int(payload.get("provider_instrument_id"))),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceReadinessError("reference manifest contains an invalid catalog record") from error


def _max_age(values: Mapping[str, str]) -> timedelta:
    raw = values.get("CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_MAX_AGE_MINUTES", "").strip()
    if not raw:
        minutes = _DEFAULT_MAX_AGE_MINUTES
    else:
        try:
            minutes = float(raw)
        except ValueError as error:
            raise ValueError("CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_MAX_AGE_MINUTES must be numeric") from error
    if minutes <= 0:
        raise ValueError("CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_MAX_AGE_MINUTES must be positive")
    return timedelta(minutes=minutes)


def _write_manifest(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def prepare_reference_readiness(
    values: MutableMapping[str, str],
    *,
    now: datetime | None = None,
    config=None,
    policy=None,
    eodhd_provider=None,
    massive_futures_provider=None,
) -> ReferenceReadinessManifest:
    """Collect and freeze the slow-changing executable reference catalogs."""

    from operations import _comprehensive_market_discovery_v4 as discovery

    timestamp = _aware(now or datetime.now(timezone.utc), field_name="now")
    release = _release(values)
    resolved_config = config or discovery._base.load_comprehensive_market_discovery_config()
    discovery._base._reject_evidence_only_eodhd_directories(resolved_config)
    resolved_policy = policy or discovery.ComprehensiveMarketDiscoveryPolicy()
    active_lanes = discovery._base.scheduled_discovery_lanes(timestamp)
    provider = eodhd_provider or discovery._base._legacy.build_eodhd_provider()

    try:
        catalogs = {
            key: list(value)
            for key, value in discovery._catalog_from_eodhd(
                as_of=timestamp,
                config=resolved_config,
                provider=provider,
                policy=resolved_policy,
                requested_asset_classes=active_lanes,
            ).items()
        }
        if CandidateAssetClass.FUTURE in active_lanes:
            catalogs[CandidateAssetClass.FUTURE] = list(
                discovery._base._legacy._futures_catalog(
                    as_of=timestamp,
                    config=resolved_config,
                    massive_futures_provider=massive_futures_provider,
                )
            )
    except Exception as error:
        raise ReferenceReadinessError(
            f"reference collection failed before the CIO cycle: {type(error).__name__}: {error}"
        ) from error

    futures_roots = tuple(
        str(item.get("root", "")).strip().upper()
        for item in resolved_config.futures_roots
        if str(item.get("root", "")).strip()
    )
    if CandidateAssetClass.FUTURE in active_lanes and futures_roots:
        future_symbols = tuple(item.symbol for item in catalogs.get(CandidateAssetClass.FUTURE, ()))
        missing_roots = tuple(
            root for root in futures_roots if not any(symbol.startswith(root) for symbol in future_symbols)
        )
        if missing_roots:
            raise ReferenceReadinessError(
                "reference futures catalog is incomplete for configured roots: " + ", ".join(missing_roots)
            )

    serial_catalogs = {
        asset_class.value: [_record_payload(item) for item in records]
        for asset_class, records in sorted(catalogs.items(), key=lambda item: item[0].value)
    }
    config_fingerprint = _fingerprint(_config_material(resolved_config))
    material: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "release": release,
        "captured_at": timestamp.isoformat(),
        "config_fingerprint": config_fingerprint,
        "eodhd_exchanges": list(resolved_config.eodhd_exchange_codes),
        "futures_roots": list(futures_roots),
        "active_lanes": sorted(item.value for item in active_lanes),
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
    return ReferenceReadinessManifest(
        manifest_id=manifest_id,
        release=release,
        captured_at=timestamp,
        config_fingerprint=config_fingerprint,
        eodhd_exchanges=tuple(resolved_config.eodhd_exchange_codes),
        futures_roots=futures_roots,
        catalog_counts=counts,
        path=path,
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
        raise ReferenceReadinessError("bound reference manifest is unavailable or invalid") from error
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

    try:
        captured_at = datetime.fromisoformat(str(payload.get("captured_at") or "").replace("Z", "+00:00"))
    except ValueError as error:
        raise ReferenceReadinessError("bound reference manifest captured_at is invalid") from error
    captured_at = _aware(captured_at, field_name="captured_at")
    age = timestamp - captured_at
    if age < timedelta(0) or age > _max_age(resolved):
        raise ReferenceReadinessError("bound reference manifest is stale for this CIO cutoff")

    if str(payload.get("config_fingerprint") or "") != _fingerprint(_config_material(config)):
        raise ReferenceReadinessError("bound reference manifest configuration does not match the CIO cycle")
    if tuple(payload.get("eodhd_exchanges") or ()) != tuple(config.eodhd_exchange_codes):
        raise ReferenceReadinessError("bound reference manifest exchange coverage does not match configuration")
    expected_roots = tuple(
        str(item.get("root", "")).strip().upper()
        for item in config.futures_roots
        if str(item.get("root", "")).strip()
    )
    if tuple(payload.get("futures_roots") or ()) != expected_roots:
        raise ReferenceReadinessError("bound reference manifest futures coverage does not match configuration")

    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, Mapping):
        raise ReferenceReadinessError("bound reference manifest catalogs are missing")
    if record_type is None:
        from operations.comprehensive_market_discovery_legacy import DiscoveryCatalogRecord
        record_type = DiscoveryCatalogRecord

    result: dict[CandidateAssetClass, tuple[object, ...]] = {}
    for raw_lane, raw_records in catalogs.items():
        try:
            asset_class = CandidateAssetClass(str(raw_lane))
        except ValueError as error:
            raise ReferenceReadinessError("bound reference manifest contains an unsupported market lane") from error
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            raise ReferenceReadinessError("bound reference manifest catalog lane must be a sequence")
        normalized = []
        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                raise ReferenceReadinessError("bound reference manifest catalog record must be an object")
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
        detail="Reference readiness failed before the bounded CIO cycle started; " + str(detail),
        values=values,
    )


__all__ = [
    "ReferenceReadinessError",
    "ReferenceReadinessManifest",
    "fail_reference_readiness_request",
    "load_reference_catalogs",
    "prepare_reference_readiness",
]
