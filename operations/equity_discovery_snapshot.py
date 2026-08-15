"""Immutable U.S.-equity discovery evidence owned by the continuous evidence plane.

The provider-backed discovery implementation remains in ``operations.equity_discovery``.
This module only persists and restores its complete result. Snapshot identity includes
held, unresolved-learning, and excluded/base-universe symbols because each affects the
canonical discovery cohort. Consumers must present the exact same scope and cannot
refresh providers through this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.equity_discovery import DiscoveredEquity, EquityDiscoveryResult

_SCHEMA = "us-equity-discovery-snapshot.v2"
_POINTER_SCHEMA = "us-equity-discovery-snapshot-pointer.v1"


class EquityDiscoverySnapshotError(RuntimeError):
    """Raised when an immutable U.S.-equity snapshot is missing or invalid."""


@dataclass(frozen=True, slots=True)
class EquityDiscoverySnapshot:
    snapshot_id: str
    evidence_as_of: datetime
    held_symbols: tuple[str, ...]
    tracked_symbols: tuple[str, ...]
    excluded_symbols: tuple[str, ...]
    result: EquityDiscoveryResult


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _symbols(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip().upper() for item in values if str(item).strip()}))


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise EquityDiscoverySnapshotError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for U.S.-equity snapshot storage"
        )
    return Path(raw).expanduser() / "continuous_evidence_plane" / "us-equity-discovery"


def _stamp(value: datetime) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", _aware(value, field_name="as_of").isoformat()).strip("-")


def _immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as error:
            raise EquityDiscoverySnapshotError("U.S.-equity snapshot cannot be read") from error
        if existing != encoded:
            raise EquityDiscoverySnapshotError(
                f"immutable U.S.-equity snapshot collision at {path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != encoded:
            raise EquityDiscoverySnapshotError(
                f"immutable U.S.-equity snapshot collision at {path.name}"
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


def publish_equity_discovery_snapshot(
    result: EquityDiscoveryResult,
    *,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
    values: Mapping[str, str] | None = None,
) -> str:
    resolved = dict(os.environ if values is None else values)
    as_of = _aware(result.as_of, field_name="equity_discovery_as_of")
    body: dict[str, object] = {
        "schema_version": _SCHEMA,
        "as_of": as_of.isoformat(),
        "state_scope": {
            "held_symbols": list(_symbols(held_symbols)),
            "tracked_symbols": list(_symbols(tracked_symbols)),
            "excluded_symbols": list(_symbols(excluded_symbols)),
        },
        "result": result.to_dict(),
        "evidence_owner": "continuous_evidence_plane",
        "release_independent": True,
        "consumer_provider_refresh_permitted": False,
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
        "snapshot_path": str(snapshot_path),
        "paper_only": True,
        "real_money_authorized": False,
    }
    _immutable_json(root / "by-as-of" / f"{_stamp(as_of)}.json", pointer)
    _atomic_json(root / "latest.json", pointer)
    return snapshot_id


def _read_payload(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot is unavailable") from error
    if not isinstance(payload, Mapping):
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot is malformed")
    return payload


def _restore_result(payload: Mapping[str, object], *, expected_as_of: datetime) -> EquityDiscoveryResult:
    try:
        if payload.get("as_of") != expected_as_of.isoformat():
            raise EquityDiscoverySnapshotError("U.S.-equity discovery cutoff mismatch")
        raw_selected = payload["selected"]
        raw_prices = payload["observed_prices"]
        raw_exclusions = payload["exclusions"]
        if not isinstance(raw_selected, list) or not isinstance(raw_prices, list) or not isinstance(raw_exclusions, list):
            raise EquityDiscoverySnapshotError("U.S.-equity discovery collections are invalid")
        selected = tuple(
            DiscoveredEquity(
                symbol=str(item["symbol"]),
                name=str(item["name"]),
                cik=str(item["cik"]),
                venue=str(item["venue"]),
                instrument_identifier=str(item["instrument_identifier"]),
                score=float(item["score"]),
                daily_return=float(item["daily_return"]),
                one_month_return=float(item["one_month_return"]),
                three_month_return=float(item["three_month_return"]),
                six_month_return=float(item["six_month_return"]),
                twelve_month_return=float(item["twelve_month_return"]),
                relative_strength=float(item["relative_strength"]),
                annualized_volatility=float(item["annualized_volatility"]),
                maximum_drawdown=float(item["maximum_drawdown"]),
                average_daily_dollar_volume=float(item["average_daily_dollar_volume"]),
                current_price=float(item["current_price"]),
                bar_count=int(item["bar_count"]),
                evidence_identifiers=tuple(str(identifier) for identifier in item["evidence_identifiers"]),
            )
            for item in raw_selected
            if isinstance(item, Mapping)
        )
        if len(selected) != len(raw_selected):
            raise EquityDiscoverySnapshotError("U.S.-equity selected evidence is invalid")
        observed_prices = tuple(
            (str(item["symbol"]), float(item["price"]), str(item["source_identifier"]))
            for item in raw_prices
            if isinstance(item, Mapping)
        )
        if len(observed_prices) != len(raw_prices):
            raise EquityDiscoverySnapshotError("U.S.-equity observed prices are invalid")
        exclusions: list[tuple[str, str]] = []
        for item in raw_exclusions:
            if not isinstance(item, list) or len(item) != 2:
                raise EquityDiscoverySnapshotError("U.S.-equity exclusion is invalid")
            exclusions.append((str(item[0]), str(item[1])))
        return EquityDiscoveryResult(
            identifier=str(payload["identifier"]),
            as_of=expected_as_of,
            policy_version=str(payload["policy_version"]),
            screened_asset_count=int(payload["screened_asset_count"]),
            snapshot_covered_count=int(payload["snapshot_covered_count"]),
            deep_shortlist_count=int(payload["deep_shortlist_count"]),
            selected=selected,
            observed_prices=observed_prices,
            exclusions=tuple(exclusions),
            security_master_snapshot_identifier=str(payload["security_master_snapshot_identifier"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EquityDiscoverySnapshotError("U.S.-equity discovery snapshot is invalid") from error


def load_equity_discovery_snapshot(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str] | None = None,
) -> EquityDiscoverySnapshot:
    resolved = dict(os.environ if values is None else values)
    expected_as_of = _aware(evidence_as_of, field_name="evidence_as_of")
    root = _root(resolved)
    pointer = _read_payload(root / "by-as-of" / f"{_stamp(expected_as_of)}.json")
    if pointer.get("schema_version") != _POINTER_SCHEMA or pointer.get("as_of") != expected_as_of.isoformat():
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot pointer is invalid")
    snapshot_id = str(pointer.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot identifier is missing")
    payload = _read_payload(root / "snapshots" / f"{snapshot_id}.json")
    if payload.get("schema_version") != _SCHEMA:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot schema is invalid")
    body = {str(key): value for key, value in payload.items() if key != "snapshot_id"}
    if payload.get("snapshot_id") != snapshot_id or _digest(body) != snapshot_id:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot integrity mismatch")
    if payload.get("consumer_provider_refresh_permitted") is not False:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot permits consumer refresh")
    scope = payload.get("state_scope")
    result_payload = payload.get("result")
    if not isinstance(scope, Mapping) or not isinstance(result_payload, Mapping):
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot scope/result is invalid")
    held_raw = scope.get("held_symbols")
    tracked_raw = scope.get("tracked_symbols")
    excluded_raw = scope.get("excluded_symbols")
    if not isinstance(held_raw, list) or not isinstance(tracked_raw, list) or not isinstance(excluded_raw, list):
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot state scope is malformed")
    held = _symbols(tuple(str(item) for item in held_raw))
    tracked = _symbols(tuple(str(item) for item in tracked_raw))
    excluded = _symbols(tuple(str(item) for item in excluded_raw))
    if list(held) != held_raw or list(tracked) != tracked_raw or list(excluded) != excluded_raw:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot state scope is not canonical")
    return EquityDiscoverySnapshot(
        snapshot_id=snapshot_id,
        evidence_as_of=expected_as_of,
        held_symbols=held,
        tracked_symbols=tracked,
        excluded_symbols=excluded,
        result=_restore_result(result_payload, expected_as_of=expected_as_of),
    )


def view_equity_discovery_snapshot(
    snapshot: EquityDiscoverySnapshot,
    *,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
) -> EquityDiscoveryResult:
    if _symbols(held_symbols) != snapshot.held_symbols:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot held-symbol scope changed")
    if _symbols(tracked_symbols) != snapshot.tracked_symbols:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot learning scope changed")
    if _symbols(excluded_symbols) != snapshot.excluded_symbols:
        raise EquityDiscoverySnapshotError("U.S.-equity snapshot base-universe exclusion scope changed")
    return snapshot.result


__all__ = [
    "EquityDiscoverySnapshot",
    "EquityDiscoverySnapshotError",
    "load_equity_discovery_snapshot",
    "publish_equity_discovery_snapshot",
    "view_equity_discovery_snapshot",
]
