"""Compact immutable handoff for provider-owned paper evidence.

Daily histories are merged into the existing row-level persistent historical store and
bound into each snapshot by per-symbol content digests.  Quotes and SEC fact payloads are
content-addressed compressed blobs, so unchanged evidence is physically deduplicated.
The snapshot manifest is immutable and release-independent.  CIO consumers reconstruct
lazy mappings from these stores without provider calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import zlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from operations.free_paper_pilot import free_paper_pilot_universe_payload
from operations.paper_evidence_spool import _canonical_bytes, _json_hook
from operations.persistent_historical_evidence import PersistentHistoricalEvidenceStore
from providers.fred import FREDObservation

_SCHEMA = "paper-evidence-snapshot.v2"
_POINTER_SCHEMA = "paper-evidence-snapshot-pointer.v1"
_HISTORY_ASSET_CLASS = "paper_evidence"
_HISTORY_PROVIDER_SCOPE = "daily_bars"


class PaperEvidenceSnapshotError(RuntimeError):
    """Raised when a compact paper-evidence snapshot cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PaperEvidenceSnapshot:
    snapshot_id: str
    evidence_as_of: datetime
    universe_signature: str
    path: Path
    payload: Mapping[str, object]


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
        raise PaperEvidenceSnapshotError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for paper evidence snapshots"
        )
    return Path(raw).expanduser() / "continuous_evidence_plane" / "paper-evidence"


def _stamp(value: datetime) -> str:
    return _aware(value, field_name="evidence_as_of").strftime("%Y%m%dT%H%M%S%fZ")


def universe_signature(universe) -> str:
    payload = free_paper_pilot_universe_payload(universe)
    instruments = payload["instruments"]
    material = {
        "schema_version": payload["schema_version"],
        "portfolio_code": payload["portfolio_code"],
        "reporting_currency": payload["reporting_currency"],
        "maximum_quote_age_minutes": payload["maximum_quote_age_minutes"],
        "instruments": sorted(
            instruments,
            key=lambda item: (str(item["instrument_identifier"]), str(item["symbol"])),
        ),
    }
    return _digest(material)


def _immutable_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise PaperEvidenceSnapshotError(
                f"immutable paper evidence collision at {path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(body)
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != body:
            raise PaperEvidenceSnapshotError(
                f"immutable paper evidence collision at {path.name}"
            )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    _immutable_bytes(
        path,
        (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        ),
    )


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


def _payload_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value, field_name="bar_timestamp")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _history_rows(raw: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    rows: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        observed = _payload_timestamp(item.get("t", item.get("observed_at")))
        if observed is None:
            continue
        rows.append(
            {
                "t": observed,
                "c": item.get("c", item.get("close")),
                "v": item.get("v", item.get("volume", 0.0)),
                "provider_kind": str(item.get("provider_kind") or "paper_evidence"),
                "source_identifier": str(
                    item.get("source_identifier")
                    or f"paper-evidence:{observed.isoformat()}"
                ),
            }
        )
    return tuple(rows)


def _history_material(rows: Sequence[Mapping[str, object]]) -> list[list[object]]:
    return [
        [
            _aware(item["t"], field_name="history_timestamp").isoformat(),  # type: ignore[arg-type]
            float(item["c"]),
            float(item.get("v", 0.0)),
        ]
        for item in rows
    ]


def _write_blob(root: Path, value: object) -> str:
    raw = _canonical_bytes(value)
    digest = hashlib.sha256(raw).hexdigest()
    _immutable_bytes(root / "blobs" / f"{digest}.zlib", zlib.compress(raw, level=6))
    return digest


def _read_blob(root: Path, digest: str) -> object:
    path = root / "blobs" / f"{digest}.zlib"
    try:
        compressed = path.read_bytes()
        raw = zlib.decompress(compressed)
    except (OSError, zlib.error) as error:
        raise PaperEvidenceSnapshotError(
            f"paper evidence blob {digest} is unavailable"
        ) from error
    if hashlib.sha256(raw).hexdigest() != digest:
        raise PaperEvidenceSnapshotError("paper evidence blob integrity mismatch")
    return json.loads(raw, object_hook=_json_hook)


class _BlobMapping(Mapping[str, object]):
    def __init__(self, root: Path, index: Mapping[str, str], *, tuple_result: bool = False) -> None:
        self._root = root
        self._index = dict(index)
        self._tuple_result = tuple_result

    def __getitem__(self, key: str) -> object:
        digest = self._index[str(key).strip().upper()]
        value = _read_blob(self._root, digest)
        if self._tuple_result and isinstance(value, list):
            return tuple(value)
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._index))

    def __len__(self) -> int:
        return len(self._index)


class _HistoryMapping(Mapping[str, object]):
    def __init__(
        self,
        *,
        evidence_as_of: datetime,
        history_index: Mapping[str, Mapping[str, object]],
        values: Mapping[str, str],
    ) -> None:
        self._as_of = evidence_as_of
        self._index = dict(history_index)
        self._store = PersistentHistoricalEvidenceStore(values)

    def __getitem__(self, key: str) -> object:
        symbol = str(key).strip().upper()
        expected = self._index[symbol]
        evidence = self._store.load(
            asset_class=_HISTORY_ASSET_CLASS,
            instrument_identity=symbol,
            provider_scope=_HISTORY_PROVIDER_SCOPE,
            as_of=self._as_of,
        )
        material = _history_material(evidence.rows)
        if len(material) != int(expected["row_count"]):
            raise PaperEvidenceSnapshotError(
                f"paper history row count changed for {symbol}"
            )
        if _digest(material) != str(expected["digest"]):
            raise PaperEvidenceSnapshotError(
                f"paper history integrity changed for {symbol}"
            )
        return tuple({"t": row[0], "c": row[1], "v": row[2]} for row in material)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._index))

    def __len__(self) -> int:
        return len(self._index)


def _macro_payload(raw_macro: Mapping[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for series, value in raw_macro.items():
        if isinstance(value, FREDObservation):
            result[str(series)] = asdict(value)
        elif isinstance(value, Mapping):
            result[str(series)] = {str(k): v for k, v in value.items()}
        else:
            raise PaperEvidenceSnapshotError(
                f"unsupported macro evidence type for {series}: {type(value).__name__}"
            )
    return result


def _restore_macro(raw: Mapping[str, object]) -> dict[str, FREDObservation]:
    result: dict[str, FREDObservation] = {}
    for series, payload in raw.items():
        if not isinstance(payload, Mapping):
            raise PaperEvidenceSnapshotError("macro snapshot entry is malformed")
        try:
            result[str(series)] = FREDObservation(
                date=str(payload["date"]),
                value=float(payload["value"]),
                realtime_start=(
                    None if payload.get("realtime_start") in (None, "") else str(payload["realtime_start"])
                ),
                realtime_end=(
                    None if payload.get("realtime_end") in (None, "") else str(payload["realtime_end"])
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PaperEvidenceSnapshotError("macro snapshot entry is invalid") from error
    return result


def publish_paper_evidence_snapshot(
    payload: Mapping[str, object],
    *,
    universe,
    evidence_as_of: datetime,
    values: Mapping[str, str],
    requested_history_days: int,
) -> PaperEvidenceSnapshot:
    """Compact one provider-owned raw payload into persistent, deduplicated stores."""

    as_of = _aware(evidence_as_of, field_name="evidence_as_of")
    bars = payload.get("bars")
    quotes = payload.get("quotes")
    macro = payload.get("macro")
    company_facts = payload.get("company_facts", {})
    if not isinstance(bars, Mapping) or not isinstance(quotes, Mapping) or not isinstance(macro, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence payload lacks bars/quotes/macro")
    if not isinstance(company_facts, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence company facts are invalid")

    history_store = PersistentHistoricalEvidenceStore(values)
    if not history_store.enabled:
        raise PaperEvidenceSnapshotError("persistent historical evidence store is disabled")
    history_index: dict[str, dict[str, object]] = {}
    for raw_symbol in bars:
        symbol = str(raw_symbol).strip().upper()
        rows = _history_rows(bars[raw_symbol])
        if not symbol or not rows:
            continue
        merged = history_store.merge(
            asset_class=_HISTORY_ASSET_CLASS,
            instrument_identity=symbol,
            provider_scope=_HISTORY_PROVIDER_SCOPE,
            rows=rows,
            requested_as_of=as_of,
            requested_history_days=requested_history_days,
        )
        material = _history_material(merged.rows)
        history_index[symbol] = {
            "row_count": len(material),
            "digest": _digest(material),
        }

    root = _root(values)
    quote_index = {
        str(symbol).strip().upper(): _write_blob(root, quotes[symbol])
        for symbol in quotes
        if str(symbol).strip()
    }
    company_index = {
        str(symbol).strip().upper(): _write_blob(root, company_facts[symbol])
        for symbol in company_facts
        if str(symbol).strip()
    }
    direct_errors = payload.get("_direct_market_errors", {})
    closed = payload.get("_scheduled_closed_symbols", ())
    if not isinstance(direct_errors, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence direct-market errors are invalid")
    if not isinstance(closed, Sequence) or isinstance(closed, (str, bytes)):
        raise PaperEvidenceSnapshotError("paper evidence closed-symbol scope is invalid")
    provider_clock = payload.get("provider_clock", {})
    if not isinstance(provider_clock, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence provider clock is invalid")

    body: dict[str, object] = {
        "schema_version": _SCHEMA,
        "evidence_as_of": as_of.isoformat(),
        "universe_signature": universe_signature(universe),
        "history_index": history_index,
        "quote_index": quote_index,
        "company_fact_index": company_index,
        "macro": _macro_payload(macro),
        "provider_clock": dict(provider_clock),
        "direct_market_errors": {
            str(symbol).strip().upper(): str(detail)
            for symbol, detail in direct_errors.items()
            if str(symbol).strip()
        },
        "scheduled_closed_symbols": sorted(
            {str(symbol).strip().upper() for symbol in closed if str(symbol).strip()}
        ),
        "evidence_owner": "continuous_evidence_plane",
        "consumer_provider_refresh_permitted": False,
        "release_independent": True,
        "investment_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    snapshot_id = _digest(body)
    manifest = {**body, "snapshot_id": snapshot_id}
    path = root / "snapshots" / f"{snapshot_id}.json"
    _immutable_json(path, manifest)
    pointer = {
        "schema_version": _POINTER_SCHEMA,
        "snapshot_id": snapshot_id,
        "evidence_as_of": as_of.isoformat(),
        "manifest_path": str(path),
        "paper_only": True,
        "real_money_authorized": False,
    }
    _immutable_json(root / "by-as-of" / f"{_stamp(as_of)}.json", pointer)
    _atomic_json(root / "latest.json", pointer)
    return load_paper_evidence_snapshot(
        evidence_as_of=as_of,
        universe=universe,
        values=values,
    )


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PaperEvidenceSnapshotError("paper evidence snapshot is unavailable") from error
    if not isinstance(payload, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence snapshot is malformed")
    return payload


def load_paper_evidence_snapshot(
    *,
    evidence_as_of: datetime,
    universe,
    values: Mapping[str, str],
) -> PaperEvidenceSnapshot:
    as_of = _aware(evidence_as_of, field_name="evidence_as_of")
    root = _root(values)
    pointer = _read_json(root / "by-as-of" / f"{_stamp(as_of)}.json")
    if pointer.get("schema_version") != _POINTER_SCHEMA or pointer.get("evidence_as_of") != as_of.isoformat():
        raise PaperEvidenceSnapshotError("paper evidence snapshot pointer is invalid")
    snapshot_id = str(pointer.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise PaperEvidenceSnapshotError("paper evidence snapshot identifier is missing")
    path = root / "snapshots" / f"{snapshot_id}.json"
    manifest = _read_json(path)
    if manifest.get("schema_version") != _SCHEMA:
        raise PaperEvidenceSnapshotError("paper evidence snapshot schema is invalid")
    body = {str(key): value for key, value in manifest.items() if key != "snapshot_id"}
    if manifest.get("snapshot_id") != snapshot_id or _digest(body) != snapshot_id:
        raise PaperEvidenceSnapshotError("paper evidence snapshot integrity mismatch")
    expected_signature = universe_signature(universe)
    if manifest.get("universe_signature") != expected_signature:
        raise PaperEvidenceSnapshotError("paper evidence universe scope changed")
    if manifest.get("consumer_provider_refresh_permitted") is not False:
        raise PaperEvidenceSnapshotError("paper evidence snapshot permits consumer refresh")

    history_index = manifest.get("history_index")
    quote_index = manifest.get("quote_index")
    company_index = manifest.get("company_fact_index")
    macro = manifest.get("macro")
    if not isinstance(history_index, Mapping) or not isinstance(quote_index, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence history/quote index is invalid")
    if not isinstance(company_index, Mapping) or not isinstance(macro, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence company/macro index is invalid")
    normalized_quotes = {str(k): str(v) for k, v in quote_index.items()}
    normalized_company = {str(k): str(v) for k, v in company_index.items()}
    direct_errors = manifest.get("direct_market_errors", {})
    closed = manifest.get("scheduled_closed_symbols", ())
    provider_clock = manifest.get("provider_clock", {})
    if not isinstance(direct_errors, Mapping) or not isinstance(provider_clock, Mapping):
        raise PaperEvidenceSnapshotError("paper evidence metadata is invalid")
    if not isinstance(closed, Sequence) or isinstance(closed, (str, bytes)):
        raise PaperEvidenceSnapshotError("paper evidence closed-symbol metadata is invalid")

    payload: Mapping[str, object] = {
        "bars": _HistoryMapping(
            evidence_as_of=as_of,
            history_index={
                str(k): v for k, v in history_index.items() if isinstance(v, Mapping)
            },
            values=values,
        ),
        "quotes": _BlobMapping(root, normalized_quotes),
        "macro": _restore_macro(macro),
        "company_facts": _BlobMapping(root, normalized_company, tuple_result=True),
        "provider_clock": dict(provider_clock),
        "_direct_market_errors": {str(k): str(v) for k, v in direct_errors.items()},
        "_scheduled_closed_symbols": tuple(str(item) for item in closed),
        "_paper_evidence_snapshot_id": snapshot_id,
    }
    return PaperEvidenceSnapshot(
        snapshot_id=snapshot_id,
        evidence_as_of=as_of,
        universe_signature=expected_signature,
        path=path,
        payload=payload,
    )


__all__ = [
    "PaperEvidenceSnapshot",
    "PaperEvidenceSnapshotError",
    "load_paper_evidence_snapshot",
    "publish_paper_evidence_snapshot",
    "universe_signature",
]
