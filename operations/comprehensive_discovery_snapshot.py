"""Immutable, restorable comprehensive-discovery snapshots.

The continuous evidence worker is the only production owner allowed to publish these
snapshots. CIO/certification consumers load an already-published snapshot at the exact
evidence cutoff and never contact discovery/reference/market-data providers through this
module.

The snapshot is deliberately release-independent. Application release identity is bound
later by the certification-input record, so a compatible new release can consume the same
qualified market snapshot without recollecting the world.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery_legacy as _legacy


_SCHEMA = "comprehensive-discovery-snapshot.v2"
_POINTER_SCHEMA = "comprehensive-discovery-snapshot-pointer.v1"


class ComprehensiveDiscoverySnapshotError(RuntimeError):
    """Raised when a qualified global discovery snapshot cannot be trusted."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise ComprehensiveDiscoverySnapshotError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for comprehensive snapshot storage"
        )
    return Path(raw).expanduser() / "continuous_evidence_plane" / "global-discovery"


def _stamp(value: datetime) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", _aware(value, field_name="as_of").isoformat()).strip("-")


def _immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ComprehensiveDiscoverySnapshotError(
                "immutable comprehensive snapshot cannot be read"
            ) from error
        if existing != encoded:
            raise ComprehensiveDiscoverySnapshotError(
                f"immutable comprehensive snapshot collision at {path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != encoded:
            raise ComprehensiveDiscoverySnapshotError(
                f"immutable comprehensive snapshot collision at {path.name}"
            )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    body = dict(payload)
    body["integrity_sha256"] = _digest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(body, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _optional_time(value: datetime | None) -> str | None:
    return None if value is None else _aware(value, field_name="timestamp").isoformat()


def _catalog_payload(item: object) -> dict[str, object]:
    catalog = getattr(item, "catalog")
    return {
        "symbol": catalog.symbol,
        "provider_symbol": catalog.provider_symbol,
        "name": catalog.name,
        "asset_class": catalog.asset_class.value,
        "economic_exposure": catalog.economic_exposure,
        "venue": catalog.venue,
        "country_code": catalog.country_code,
        "currency": catalog.currency,
        "settlement_currency": catalog.settlement_currency,
        "instrument_type": catalog.instrument_type,
        "provider_kind": catalog.provider_kind,
        "source_identifier": catalog.source_identifier,
        "instrument_identifier": catalog.instrument_identifier,
        "contract_multiplier": catalog.contract_multiplier,
        "quote_spread_bps": catalog.quote_spread_bps,
        "expiration_at": _optional_time(catalog.expiration_at),
        "underlying_symbol": catalog.underlying_symbol,
        "strike": catalog.strike,
        "option_right": catalog.option_right,
        "provider_dataset": catalog.provider_dataset,
        "provider_stype_in": catalog.provider_stype_in,
        "provider_instrument_id": catalog.provider_instrument_id,
    }


def _feature_payload(item: object) -> dict[str, object]:
    features = getattr(item, "features")
    return {
        "price": features.price,
        "observed_at": _aware(features.observed_at, field_name="observed_at").isoformat(),
        "one_month_return": features.one_month_return,
        "three_month_return": features.three_month_return,
        "six_month_return": features.six_month_return,
        "twelve_month_return": features.twelve_month_return,
        "annualized_volatility": features.annualized_volatility,
        "maximum_drawdown": features.maximum_drawdown,
        "average_daily_dollar_volume": features.average_daily_dollar_volume,
        "history_bars": features.history_bars,
        "evidence_identifiers": list(features.evidence_identifiers),
    }


def _lane_payload(lane: object) -> dict[str, object]:
    preselection_evidence = getattr(lane, "preselection_evidence", ())
    return {
        "asset_class": lane.asset_class.value,
        "catalog_count": int(lane.catalog_count),
        "deep_analyzed_count": int(lane.deep_analyzed_count),
        "continuity_count": int(getattr(lane, "continuity_count", 0)),
        "selected": [
            {
                "catalog": _catalog_payload(item),
                "features": _feature_payload(item),
                "retained_for_state": bool(item.retained_for_state),
            }
            for item in lane.selected
        ],
        "exclusions": [[str(symbol), str(reason)] for symbol, reason in lane.exclusions],
        "source_identifiers": [str(item) for item in lane.source_identifiers],
        "scheduled": bool(lane.scheduled),
        "schedule_reason": lane.schedule_reason,
        "preselection_evidence": [
            [str(symbol), [str(identifier) for identifier in identifiers]]
            for symbol, identifiers in preselection_evidence
        ],
    }


def publish_comprehensive_discovery_snapshot(
    result: object,
    *,
    values: Mapping[str, str] | None = None,
) -> str:
    """Publish one release-independent global discovery result immutably."""

    resolved = dict(os.environ if values is None else values)
    as_of = _aware(getattr(result, "as_of"), field_name="discovery_as_of")
    lanes = tuple(getattr(result, "lanes"))
    body: dict[str, object] = {
        "schema_version": _SCHEMA,
        "as_of": as_of.isoformat(),
        "identifier": str(getattr(result, "identifier")),
        "policy_version": str(getattr(result, "policy_version")),
        "manifest_fingerprint": str(getattr(result, "manifest_fingerprint")),
        "scheduled_lanes": [
            lane.asset_class.value for lane in lanes if bool(lane.scheduled)
        ],
        "lanes": [_lane_payload(lane) for lane in lanes],
        "evidence_owner": "continuous_evidence_plane",
        "release_independent": True,
        "consumer_provider_refresh_permitted": False,
        "candidate_count_limit_applied": False,
        "investment_authority": False,
        "specialist_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    snapshot_id = _digest(body)
    payload = {**body, "snapshot_id": snapshot_id}
    root = _root(resolved)
    snapshot_path = root / "snapshots" / f"{snapshot_id}.json"
    _immutable_json(snapshot_path, payload)
    pointer = {
        "schema_version": _POINTER_SCHEMA,
        "snapshot_id": snapshot_id,
        "as_of": as_of.isoformat(),
        "manifest_fingerprint": body["manifest_fingerprint"],
        "snapshot_path": str(snapshot_path),
        "paper_only": True,
        "real_money_authorized": False,
    }
    # Same evidence cutoff must be deterministic. A second different result for the
    # exact same cutoff is a certification failure, not a mutable replacement.
    _immutable_json(root / "by-as-of" / f"{_stamp(as_of)}.json", pointer)
    _atomic_json(root / "latest.json", pointer)
    return snapshot_id


def _read_pointer(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot pointer is unavailable"
        ) from error
    if not isinstance(payload, Mapping):
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot pointer is malformed"
        )
    return payload


def _read_snapshot(path: Path, *, expected_id: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot is unavailable"
        ) from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _SCHEMA:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot schema is invalid"
        )
    body = {str(key): value for key, value in payload.items() if key != "snapshot_id"}
    if payload.get("snapshot_id") != expected_id or _digest(body) != expected_id:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot integrity mismatch"
        )
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot authority boundary is invalid"
        )
    if payload.get("consumer_provider_refresh_permitted") is not False:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot permits consumer refresh"
        )
    return payload


def _parse_optional_time(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ComprehensiveDiscoverySnapshotError("snapshot timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ComprehensiveDiscoverySnapshotError("snapshot timestamp is invalid") from error
    return _aware(parsed, field_name="snapshot_timestamp")


def _finite_number(payload: Mapping[str, object], name: str) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComprehensiveDiscoverySnapshotError(f"snapshot {name} is invalid")
    number = float(value)
    if not math.isfinite(number):
        raise ComprehensiveDiscoverySnapshotError(f"snapshot {name} is invalid")
    return number


def _restore_catalog(payload: Mapping[str, object]) -> _legacy.DiscoveryCatalogRecord:
    try:
        asset_class = CandidateAssetClass(str(payload["asset_class"]))
        provider_instrument_id = payload.get("provider_instrument_id")
        if provider_instrument_id is not None:
            provider_instrument_id = int(provider_instrument_id)
        strike = payload.get("strike")
        if strike is not None:
            strike = float(strike)
        return _legacy.DiscoveryCatalogRecord(
            symbol=str(payload["symbol"]),
            provider_symbol=str(payload["provider_symbol"]),
            name=str(payload["name"]),
            asset_class=asset_class,
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
                else str(payload["instrument_identifier"])
            ),
            contract_multiplier=_finite_number(payload, "contract_multiplier"),
            quote_spread_bps=_finite_number(payload, "quote_spread_bps"),
            expiration_at=_parse_optional_time(payload.get("expiration_at")),
            underlying_symbol=(
                None if payload.get("underlying_symbol") in (None, "") else str(payload["underlying_symbol"])
            ),
            strike=strike,
            option_right=(
                None if payload.get("option_right") in (None, "") else str(payload["option_right"])
            ),
            provider_dataset=(
                None if payload.get("provider_dataset") in (None, "") else str(payload["provider_dataset"])
            ),
            provider_stype_in=(
                None if payload.get("provider_stype_in") in (None, "") else str(payload["provider_stype_in"])
            ),
            provider_instrument_id=provider_instrument_id,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ComprehensiveDiscoverySnapshotError(
            "snapshot contains an invalid catalog record"
        ) from error


def _restore_features(payload: Mapping[str, object]) -> _legacy.DiscoveryMarketFeatures:
    identifiers = payload.get("evidence_identifiers")
    if not isinstance(identifiers, Sequence) or isinstance(identifiers, (str, bytes)):
        raise ComprehensiveDiscoverySnapshotError(
            "snapshot evidence identifiers are invalid"
        )
    observed_at = _parse_optional_time(payload.get("observed_at"))
    if observed_at is None:
        raise ComprehensiveDiscoverySnapshotError("snapshot observed_at is missing")
    try:
        history_bars = int(payload["history_bars"])
    except (KeyError, TypeError, ValueError) as error:
        raise ComprehensiveDiscoverySnapshotError("snapshot history_bars is invalid") from error
    return _legacy.DiscoveryMarketFeatures(
        price=_finite_number(payload, "price"),
        observed_at=observed_at,
        one_month_return=_finite_number(payload, "one_month_return"),
        three_month_return=_finite_number(payload, "three_month_return"),
        six_month_return=_finite_number(payload, "six_month_return"),
        twelve_month_return=_finite_number(payload, "twelve_month_return"),
        annualized_volatility=_finite_number(payload, "annualized_volatility"),
        maximum_drawdown=_finite_number(payload, "maximum_drawdown"),
        average_daily_dollar_volume=_finite_number(payload, "average_daily_dollar_volume"),
        history_bars=history_bars,
        evidence_identifiers=tuple(str(item) for item in identifiers),
    )


def _restore_lane(payload: Mapping[str, object]) -> _legacy.DiscoveryLaneResult:
    raw_selected = payload.get("selected")
    raw_exclusions = payload.get("exclusions")
    raw_sources = payload.get("source_identifiers")
    if not isinstance(raw_selected, list) or not isinstance(raw_exclusions, list) or not isinstance(raw_sources, list):
        raise ComprehensiveDiscoverySnapshotError("snapshot lane collections are invalid")
    selected = []
    for item in raw_selected:
        if not isinstance(item, Mapping) or not isinstance(item.get("catalog"), Mapping) or not isinstance(item.get("features"), Mapping):
            raise ComprehensiveDiscoverySnapshotError("snapshot selected instrument is invalid")
        selected.append(
            _legacy.DiscoveredMarketInstrument(
                catalog=_restore_catalog(item["catalog"]),
                features=_restore_features(item["features"]),
                retained_for_state=bool(item.get("retained_for_state", False)),
            )
        )
    exclusions: list[tuple[str, str]] = []
    for item in raw_exclusions:
        if not isinstance(item, list) or len(item) != 2:
            raise ComprehensiveDiscoverySnapshotError("snapshot exclusion is invalid")
        exclusions.append((str(item[0]), str(item[1])))
    try:
        return _legacy.DiscoveryLaneResult(
            asset_class=CandidateAssetClass(str(payload["asset_class"])),
            catalog_count=int(payload["catalog_count"]),
            deep_analyzed_count=int(payload["deep_analyzed_count"]),
            selected=tuple(selected),
            exclusions=tuple(exclusions),
            source_identifiers=tuple(str(item) for item in raw_sources),
            scheduled=bool(payload.get("scheduled", True)),
            schedule_reason=(
                None if payload.get("schedule_reason") in (None, "") else str(payload["schedule_reason"])
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ComprehensiveDiscoverySnapshotError("snapshot lane is invalid") from error


def load_comprehensive_discovery_snapshot(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str] | None = None,
) -> tuple[str, _legacy.ComprehensiveMarketDiscoveryResult]:
    """Load the exact evidence-cutoff global snapshot without any provider fallback."""

    resolved = dict(os.environ if values is None else values)
    expected_as_of = _aware(evidence_as_of, field_name="evidence_as_of")
    root = _root(resolved)
    pointer = _read_pointer(root / "by-as-of" / f"{_stamp(expected_as_of)}.json")
    if pointer.get("schema_version") != _POINTER_SCHEMA:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot pointer schema is invalid"
        )
    if pointer.get("as_of") != expected_as_of.isoformat():
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot cutoff mismatch"
        )
    snapshot_id = str(pointer.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot identifier is missing"
        )
    payload = _read_snapshot(
        root / "snapshots" / f"{snapshot_id}.json",
        expected_id=snapshot_id,
    )
    if payload.get("as_of") != expected_as_of.isoformat():
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot evidence cutoff changed"
        )
    raw_lanes = payload.get("lanes")
    if not isinstance(raw_lanes, list):
        raise ComprehensiveDiscoverySnapshotError("snapshot lanes are invalid")
    lanes = tuple(
        _restore_lane(item)
        for item in raw_lanes
        if isinstance(item, Mapping)
    )
    if len(lanes) != len(raw_lanes):
        raise ComprehensiveDiscoverySnapshotError("snapshot contains an invalid lane")
    result = _legacy.ComprehensiveMarketDiscoveryResult(
        identifier=str(payload.get("identifier") or ""),
        as_of=expected_as_of,
        policy_version=str(payload.get("policy_version") or ""),
        lanes=lanes,
        manifest_fingerprint=str(payload.get("manifest_fingerprint") or ""),
    )
    if not result.identifier or not result.policy_version or not result.manifest_fingerprint:
        raise ComprehensiveDiscoverySnapshotError(
            "snapshot discovery identity is incomplete"
        )
    return snapshot_id, result


__all__ = [
    "ComprehensiveDiscoverySnapshotError",
    "load_comprehensive_discovery_snapshot",
    "publish_comprehensive_discovery_snapshot",
]
