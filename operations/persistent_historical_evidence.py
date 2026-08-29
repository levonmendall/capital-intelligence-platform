"""Persistent point-in-time historical evidence shared by executable asset lanes.

Historical observations are retained as append-only row versions and each refresh creates
an immutable snapshot boundary. Reads select the newest snapshot whose request boundary
is at or before the decision epoch, so a later refresh cannot rewrite evidence lineage for
an earlier decision. The legacy mutable projection is retained only for deploy/rollback
compatibility and is conservatively imported at its recorded request boundary; it is never
backdated.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from providers.redundant_market_history import (
    MarketHistoryCandidate,
    RedundantMarketHistoryRouter,
)

_SCHEMA_VERSION = "persistent-historical-evidence.v1"
_SNAPSHOT_SCHEMA_VERSION = "persistent-historical-evidence-snapshots.v1"
_DEFAULT_MAX_AGE_HOURS = 18.0
_MINIMUM_DELTA_DAYS = 7
_DELTA_OVERLAP_DAYS = 3


class PersistentHistoricalEvidenceError(RuntimeError):
    """Raised when persisted history cannot be trusted."""


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceSlice:
    rows: tuple[dict[str, object], ...]
    maximum_history_days: int
    requested_as_of: datetime | None


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("historical evidence timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _max_age_hours(values: Mapping[str, str]) -> float:
    raw = values.get("CAPITAL_INTELLIGENCE_HISTORICAL_BASE_MAX_AGE_HOURS", "").strip()
    if not raw:
        return _DEFAULT_MAX_AGE_HOURS
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_HISTORICAL_BASE_MAX_AGE_HOURS must be numeric"
        ) from error
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_HISTORICAL_BASE_MAX_AGE_HOURS must be positive"
        )
    return value


def _asset_class_from_capability(capability: str) -> str:
    normalized = str(capability or "").strip().lower()
    if normalized.startswith("us_equity"):
        return "us_equity_or_etf"
    if normalized.startswith("international_equity"):
        return "international_equity"
    if normalized.startswith("fx_") or normalized == "fx_history":
        return "fx"
    if normalized.startswith("crypto"):
        return "crypto"
    if normalized.startswith("futures") or normalized.startswith("future"):
        return "future"
    if normalized.startswith("fixed_income"):
        return "fixed_income"
    return "market"


def _normalize_mapping_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    as_of: datetime,
) -> tuple[dict[str, object], ...]:
    timestamp = _aware(as_of)
    by_time: dict[datetime, dict[str, object]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        observed_raw = raw.get("t", raw.get("observed_at"))
        if not isinstance(observed_raw, datetime):
            continue
        observed = _aware(observed_raw)
        if observed > timestamp:
            raise PersistentHistoricalEvidenceError(
                "historical evidence contains an observation after the decision epoch"
            )
        close_raw = raw.get("c", raw.get("close"))
        volume_raw = raw.get("v", raw.get("volume", 0.0))
        try:
            close = float(close_raw)  # type: ignore[arg-type]
            volume = max(0.0, float(volume_raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0.0 or not math.isfinite(volume):
            continue
        item: dict[str, object] = {"t": observed, "c": close, "v": volume}
        provider_kind = str(raw.get("provider_kind") or "").strip()
        source_identifier = str(raw.get("source_identifier") or "").strip()
        if provider_kind:
            item["provider_kind"] = provider_kind
        if source_identifier:
            item["source_identifier"] = source_identifier
        by_time[observed] = item
    return tuple(by_time[key] for key in sorted(by_time))


class PersistentHistoricalEvidenceStore:
    """SQLite store with immutable refresh snapshots and append-only row versions."""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(os.environ if values is None else values)
        raw = self._values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
        self.path = (
            None
            if not raw
            else Path(raw).expanduser() / "historical_evidence" / "market_history.sqlite3"
        )

    @property
    def enabled(self) -> bool:
        return self.path is not None

    @property
    def max_age_hours(self) -> float:
        return _max_age_hours(self._values)

    def _connect(self) -> sqlite3.Connection:
        if self.path is None:
            raise PersistentHistoricalEvidenceError("persistent historical evidence is disabled")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_evidence_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # Keep the legacy v1 projection for rollback compatibility. New code never
        # treats it as historical truth before its recorded requested_as_of boundary.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_evidence_rows (
                asset_class TEXT NOT NULL,
                instrument_identity TEXT NOT NULL,
                provider_scope TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                provider_kind TEXT NOT NULL,
                source_identifier TEXT NOT NULL,
                integrity_sha256 TEXT NOT NULL,
                PRIMARY KEY (
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    observed_at
                )
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_evidence_coverage (
                asset_class TEXT NOT NULL,
                instrument_identity TEXT NOT NULL,
                provider_scope TEXT NOT NULL,
                maximum_history_days INTEGER NOT NULL,
                requested_as_of TEXT NOT NULL,
                integrity_sha256 TEXT NOT NULL,
                PRIMARY KEY (asset_class, instrument_identity, provider_scope)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_evidence_snapshots (
                snapshot_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_class TEXT NOT NULL,
                instrument_identity TEXT NOT NULL,
                provider_scope TEXT NOT NULL,
                maximum_history_days INTEGER NOT NULL,
                requested_as_of TEXT NOT NULL,
                integrity_sha256 TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS historical_evidence_snapshots_scope_epoch
            ON historical_evidence_snapshots(
                asset_class,
                instrument_identity,
                provider_scope,
                requested_as_of,
                snapshot_sequence
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_evidence_row_versions (
                snapshot_sequence INTEGER NOT NULL,
                asset_class TEXT NOT NULL,
                instrument_identity TEXT NOT NULL,
                provider_scope TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                provider_kind TEXT NOT NULL,
                source_identifier TEXT NOT NULL,
                integrity_sha256 TEXT NOT NULL,
                PRIMARY KEY (
                    snapshot_sequence,
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    observed_at
                ),
                FOREIGN KEY(snapshot_sequence)
                    REFERENCES historical_evidence_snapshots(snapshot_sequence)
                    ON DELETE RESTRICT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS historical_evidence_row_versions_lookup
            ON historical_evidence_row_versions(
                asset_class,
                instrument_identity,
                provider_scope,
                observed_at,
                snapshot_sequence
            )
            """
        )
        existing = connection.execute(
            "SELECT value FROM historical_evidence_meta WHERE key='schema_version'"
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO historical_evidence_meta(key, value) VALUES('schema_version', ?)",
                (_SCHEMA_VERSION,),
            )
        elif existing[0] != _SCHEMA_VERSION:
            connection.close()
            raise PersistentHistoricalEvidenceError(
                "persistent historical evidence schema mismatch"
            )
        snapshot_schema = connection.execute(
            "SELECT value FROM historical_evidence_meta WHERE key='snapshot_schema_version'"
        ).fetchone()
        if snapshot_schema is None:
            connection.execute(
                "INSERT INTO historical_evidence_meta(key, value) "
                "VALUES('snapshot_schema_version', ?)",
                (_SNAPSHOT_SCHEMA_VERSION,),
            )
        elif snapshot_schema[0] != _SNAPSHOT_SCHEMA_VERSION:
            connection.close()
            raise PersistentHistoricalEvidenceError(
                "persistent historical evidence snapshot schema mismatch"
            )
        connection.commit()
        return connection

    @staticmethod
    def _coverage_payload(
        *,
        asset_class: str,
        instrument_identity: str,
        provider_scope: str,
        maximum_history_days: int,
        requested_as_of: str,
    ) -> dict[str, object]:
        return {
            "asset_class": asset_class,
            "instrument_identity": instrument_identity,
            "provider_scope": provider_scope,
            "maximum_history_days": int(maximum_history_days),
            "requested_as_of": str(requested_as_of),
        }

    @staticmethod
    def _row_payload(
        *,
        asset_class: str,
        instrument_identity: str,
        provider_scope: str,
        observed_at: str,
        close: float,
        volume: float,
        provider_kind: str,
        source_identifier: str,
    ) -> dict[str, object]:
        return {
            "asset_class": asset_class,
            "instrument_identity": instrument_identity,
            "provider_scope": provider_scope,
            "observed_at": str(observed_at),
            "close": float(close),
            "volume": float(volume),
            "provider_kind": str(provider_kind),
            "source_identifier": str(source_identifier),
        }

    def _append_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        asset_class: str,
        instrument_identity: str,
        provider_scope: str,
        maximum_history_days: int,
        requested_as_of: datetime,
        rows: Sequence[Mapping[str, object]],
    ) -> int:
        timestamp = _aware(requested_as_of)
        latest = connection.execute(
            """
            SELECT requested_as_of
            FROM historical_evidence_snapshots
            WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
            ORDER BY requested_as_of DESC, snapshot_sequence DESC
            LIMIT 1
            """,
            (asset_class, instrument_identity, provider_scope),
        ).fetchone()
        if latest is not None:
            latest_requested = _aware(datetime.fromisoformat(str(latest[0])))
            if latest_requested > timestamp:
                raise PersistentHistoricalEvidenceError(
                    "cannot append persistent historical evidence before the latest "
                    "persisted snapshot epoch"
                )

        coverage_payload = self._coverage_payload(
            asset_class=asset_class,
            instrument_identity=instrument_identity,
            provider_scope=provider_scope,
            maximum_history_days=maximum_history_days,
            requested_as_of=timestamp.isoformat(),
        )
        cursor = connection.execute(
            """
            INSERT INTO historical_evidence_snapshots(
                asset_class, instrument_identity, provider_scope,
                maximum_history_days, requested_as_of, integrity_sha256
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                asset_class,
                instrument_identity,
                provider_scope,
                int(maximum_history_days),
                timestamp.isoformat(),
                _digest(coverage_payload),
            ),
        )
        snapshot_sequence = int(cursor.lastrowid)
        for item in rows:
            observed = _aware(item["t"])  # type: ignore[arg-type]
            provider_kind = str(item.get("provider_kind") or "")
            source_identifier = str(item.get("source_identifier") or "")
            payload = self._row_payload(
                asset_class=asset_class,
                instrument_identity=instrument_identity,
                provider_scope=provider_scope,
                observed_at=observed.isoformat(),
                close=float(item["c"]),
                volume=float(item.get("v", 0.0)),
                provider_kind=provider_kind,
                source_identifier=source_identifier,
            )
            connection.execute(
                """
                INSERT INTO historical_evidence_row_versions(
                    snapshot_sequence, asset_class, instrument_identity, provider_scope,
                    observed_at, close, volume, provider_kind, source_identifier,
                    integrity_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_sequence,
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    observed.isoformat(),
                    float(item["c"]),
                    float(item.get("v", 0.0)),
                    provider_kind,
                    source_identifier,
                    _digest(payload),
                ),
            )
        return snapshot_sequence

    def _sync_legacy_scope(
        self,
        connection: sqlite3.Connection,
        *,
        asset_class: str,
        instrument_identity: str,
        provider_scope: str,
    ) -> None:
        legacy = connection.execute(
            """
            SELECT maximum_history_days, requested_as_of, integrity_sha256
            FROM historical_evidence_coverage
            WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
            """,
            (asset_class, instrument_identity, provider_scope),
        ).fetchone()
        if legacy is None:
            return
        maximum_days, requested_raw, integrity = legacy
        coverage_payload = self._coverage_payload(
            asset_class=asset_class,
            instrument_identity=instrument_identity,
            provider_scope=provider_scope,
            maximum_history_days=int(maximum_days),
            requested_as_of=str(requested_raw),
        )
        if integrity != _digest(coverage_payload):
            raise PersistentHistoricalEvidenceError(
                "persistent historical evidence coverage integrity mismatch"
            )
        requested = _aware(datetime.fromisoformat(str(requested_raw)))
        latest = connection.execute(
            """
            SELECT requested_as_of
            FROM historical_evidence_snapshots
            WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
            ORDER BY requested_as_of DESC, snapshot_sequence DESC
            LIMIT 1
            """,
            (asset_class, instrument_identity, provider_scope),
        ).fetchone()
        if latest is not None:
            latest_requested = _aware(datetime.fromisoformat(str(latest[0])))
            if latest_requested >= requested:
                return

        legacy_rows = connection.execute(
            """
            SELECT observed_at, close, volume, provider_kind, source_identifier,
                   integrity_sha256
            FROM historical_evidence_rows
            WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
            ORDER BY observed_at
            """,
            (asset_class, instrument_identity, provider_scope),
        ).fetchall()
        material: list[dict[str, object]] = []
        for observed_raw, close, volume, provider_kind, source_identifier, row_integrity in legacy_rows:
            payload = self._row_payload(
                asset_class=asset_class,
                instrument_identity=instrument_identity,
                provider_scope=provider_scope,
                observed_at=str(observed_raw),
                close=float(close),
                volume=float(volume),
                provider_kind=str(provider_kind),
                source_identifier=str(source_identifier),
            )
            if row_integrity != _digest(payload):
                raise PersistentHistoricalEvidenceError(
                    "persistent historical evidence row integrity mismatch"
                )
            observed = _aware(datetime.fromisoformat(str(observed_raw)))
            if observed > requested:
                raise PersistentHistoricalEvidenceError(
                    "legacy persistent historical evidence contains an observation "
                    "after its recorded request boundary"
                )
            item: dict[str, object] = {
                "t": observed,
                "c": float(close),
                "v": float(volume),
            }
            if provider_kind:
                item["provider_kind"] = str(provider_kind)
            if source_identifier:
                item["source_identifier"] = str(source_identifier)
            material.append(item)
        self._append_snapshot(
            connection,
            asset_class=asset_class,
            instrument_identity=instrument_identity,
            provider_scope=provider_scope,
            maximum_history_days=int(maximum_days),
            requested_as_of=requested,
            rows=tuple(material),
        )

    def _selected_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        asset_class: str,
        instrument_identity: str,
        provider_scope: str,
        as_of: datetime,
    ) -> tuple[int, int, datetime] | None:
        timestamp = _aware(as_of)
        selected = connection.execute(
            """
            SELECT snapshot_sequence, maximum_history_days, requested_as_of,
                   integrity_sha256
            FROM historical_evidence_snapshots
            WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
              AND requested_as_of<=?
            ORDER BY requested_as_of DESC, snapshot_sequence DESC
            LIMIT 1
            """,
            (
                asset_class,
                instrument_identity,
                provider_scope,
                timestamp.isoformat(),
            ),
        ).fetchone()
        if selected is None:
            later = connection.execute(
                """
                SELECT requested_as_of
                FROM historical_evidence_snapshots
                WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
                ORDER BY requested_as_of ASC, snapshot_sequence ASC
                LIMIT 1
                """,
                (asset_class, instrument_identity, provider_scope),
            ).fetchone()
            if later is not None:
                raise PersistentHistoricalEvidenceError(
                    "persistent historical evidence was refreshed after the decision epoch; "
                    f"asset_class={asset_class}; "
                    f"instrument_identity={instrument_identity}; "
                    f"provider_scope={provider_scope}; "
                    f"decision_epoch={timestamp.isoformat()}; "
                    f"earliest_available_requested_as_of={later[0]}"
                )
            return None
        snapshot_sequence, maximum_days, requested_raw, integrity = selected
        payload = self._coverage_payload(
            asset_class=asset_class,
            instrument_identity=instrument_identity,
            provider_scope=provider_scope,
            maximum_history_days=int(maximum_days),
            requested_as_of=str(requested_raw),
        )
        if integrity != _digest(payload):
            raise PersistentHistoricalEvidenceError(
                "persistent historical evidence snapshot integrity mismatch"
            )
        requested = _aware(datetime.fromisoformat(str(requested_raw)))
        return int(snapshot_sequence), int(maximum_days), requested

    def load(
        self,
        *,
        asset_class: str,
        instrument_identity: str,
        provider_scope: str,
        as_of: datetime,
    ) -> HistoricalEvidenceSlice:
        if not self.enabled:
            return HistoricalEvidenceSlice((), 0, None)
        timestamp = _aware(as_of)
        connection = self._connect()
        try:
            with connection:
                self._sync_legacy_scope(
                    connection,
                    asset_class=asset_class,
                    instrument_identity=instrument_identity,
                    provider_scope=provider_scope,
                )
            selected = self._selected_snapshot(
                connection,
                asset_class=asset_class,
                instrument_identity=instrument_identity,
                provider_scope=provider_scope,
                as_of=timestamp,
            )
            if selected is None:
                return HistoricalEvidenceSlice((), 0, None)
            snapshot_sequence, maximum_days, requested = selected
            rows = connection.execute(
                """
                SELECT versions.observed_at, versions.close, versions.volume,
                       versions.provider_kind, versions.source_identifier,
                       versions.integrity_sha256
                FROM historical_evidence_row_versions AS versions
                WHERE versions.asset_class=?
                  AND versions.instrument_identity=?
                  AND versions.provider_scope=?
                  AND versions.observed_at<=?
                  AND versions.snapshot_sequence=(
                      SELECT MAX(candidate.snapshot_sequence)
                      FROM historical_evidence_row_versions AS candidate
                      WHERE candidate.asset_class=versions.asset_class
                        AND candidate.instrument_identity=versions.instrument_identity
                        AND candidate.provider_scope=versions.provider_scope
                        AND candidate.observed_at=versions.observed_at
                        AND candidate.snapshot_sequence<=?
                  )
                ORDER BY versions.observed_at
                """,
                (
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    timestamp.isoformat(),
                    snapshot_sequence,
                ),
            ).fetchall()
            material: list[dict[str, object]] = []
            for observed_raw, close, volume, provider_kind, source_identifier, integrity in rows:
                payload = self._row_payload(
                    asset_class=asset_class,
                    instrument_identity=instrument_identity,
                    provider_scope=provider_scope,
                    observed_at=str(observed_raw),
                    close=float(close),
                    volume=float(volume),
                    provider_kind=str(provider_kind),
                    source_identifier=str(source_identifier),
                )
                if integrity != _digest(payload):
                    raise PersistentHistoricalEvidenceError(
                        "persistent historical evidence row integrity mismatch"
                    )
                observed = _aware(datetime.fromisoformat(str(observed_raw)))
                item: dict[str, object] = {
                    "t": observed,
                    "c": float(close),
                    "v": float(volume),
                }
                if provider_kind:
                    item["provider_kind"] = str(provider_kind)
                if source_identifier:
                    item["source_identifier"] = str(source_identifier)
                material.append(item)
            return HistoricalEvidenceSlice(tuple(material), maximum_days, requested)
        finally:
            connection.close()

    def merge(
        self,
        *,
        asset_class: str,
        instrument_identity: str,
        provider_scope: str,
        rows: Sequence[Mapping[str, object]],
        requested_as_of: datetime,
        requested_history_days: int = 0,
    ) -> HistoricalEvidenceSlice:
        if not self.enabled:
            normalized = _normalize_mapping_rows(rows, as_of=requested_as_of)
            return HistoricalEvidenceSlice(
                normalized,
                max(0, requested_history_days),
                _aware(requested_as_of),
            )
        timestamp = _aware(requested_as_of)
        normalized = _normalize_mapping_rows(rows, as_of=timestamp)
        connection = self._connect()
        try:
            with connection:
                self._sync_legacy_scope(
                    connection,
                    asset_class=asset_class,
                    instrument_identity=instrument_identity,
                    provider_scope=provider_scope,
                )
                latest = connection.execute(
                    """
                    SELECT maximum_history_days, requested_as_of
                    FROM historical_evidence_snapshots
                    WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
                    ORDER BY requested_as_of DESC, snapshot_sequence DESC
                    LIMIT 1
                    """,
                    (asset_class, instrument_identity, provider_scope),
                ).fetchone()
                if latest is not None:
                    latest_requested = _aware(datetime.fromisoformat(str(latest[1])))
                    if latest_requested > timestamp:
                        raise PersistentHistoricalEvidenceError(
                            "cannot backdate persistent historical evidence refresh; "
                            f"instrument_identity={instrument_identity}; "
                            f"requested_as_of={timestamp.isoformat()}; "
                            f"latest_snapshot_requested_as_of={latest_requested.isoformat()}"
                        )
                maximum_days = max(
                    int(latest[0]) if latest is not None else 0,
                    max(0, int(requested_history_days)),
                )
                self._append_snapshot(
                    connection,
                    asset_class=asset_class,
                    instrument_identity=instrument_identity,
                    provider_scope=provider_scope,
                    maximum_history_days=maximum_days,
                    requested_as_of=timestamp,
                    rows=normalized,
                )

                # Maintain the v1 projection for rollback compatibility. It is not used
                # as point-in-time truth once a snapshot exists.
                for item in normalized:
                    observed = _aware(item["t"])  # type: ignore[arg-type]
                    provider_kind = str(item.get("provider_kind") or "")
                    source_identifier = str(item.get("source_identifier") or "")
                    payload = self._row_payload(
                        asset_class=asset_class,
                        instrument_identity=instrument_identity,
                        provider_scope=provider_scope,
                        observed_at=observed.isoformat(),
                        close=float(item["c"]),
                        volume=float(item.get("v", 0.0)),
                        provider_kind=provider_kind,
                        source_identifier=source_identifier,
                    )
                    connection.execute(
                        """
                        INSERT INTO historical_evidence_rows(
                            asset_class, instrument_identity, provider_scope, observed_at,
                            close, volume, provider_kind, source_identifier,
                            integrity_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(asset_class, instrument_identity, provider_scope, observed_at)
                        DO UPDATE SET close=excluded.close, volume=excluded.volume,
                                      provider_kind=excluded.provider_kind,
                                      source_identifier=excluded.source_identifier,
                                      integrity_sha256=excluded.integrity_sha256
                        """,
                        (
                            asset_class,
                            instrument_identity,
                            provider_scope,
                            observed.isoformat(),
                            float(item["c"]),
                            float(item.get("v", 0.0)),
                            provider_kind,
                            source_identifier,
                            _digest(payload),
                        ),
                    )
                coverage_payload = self._coverage_payload(
                    asset_class=asset_class,
                    instrument_identity=instrument_identity,
                    provider_scope=provider_scope,
                    maximum_history_days=maximum_days,
                    requested_as_of=timestamp.isoformat(),
                )
                connection.execute(
                    """
                    INSERT INTO historical_evidence_coverage(
                        asset_class, instrument_identity, provider_scope,
                        maximum_history_days, requested_as_of, integrity_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_class, instrument_identity, provider_scope)
                    DO UPDATE SET maximum_history_days=excluded.maximum_history_days,
                                  requested_as_of=excluded.requested_as_of,
                                  integrity_sha256=excluded.integrity_sha256
                    """,
                    (
                        asset_class,
                        instrument_identity,
                        provider_scope,
                        maximum_days,
                        timestamp.isoformat(),
                        _digest(coverage_payload),
                    ),
                )
        finally:
            connection.close()
        return self.load(
            asset_class=asset_class,
            instrument_identity=instrument_identity,
            provider_scope=provider_scope,
            as_of=timestamp,
        )


def _is_recent(
    evidence: HistoricalEvidenceSlice,
    *,
    as_of: datetime,
    max_age_hours: float,
) -> bool:
    if evidence.requested_as_of is None:
        return False
    age = _aware(as_of) - evidence.requested_as_of
    return timedelta(0) <= age <= timedelta(hours=max_age_hours)


def _delta_history_days(evidence: HistoricalEvidenceSlice, *, as_of: datetime) -> int:
    if evidence.requested_as_of is None:
        return _MINIMUM_DELTA_DAYS
    age_days = max(
        0,
        math.ceil((_aware(as_of) - evidence.requested_as_of).total_seconds() / 86400.0),
    )
    return max(_MINIMUM_DELTA_DAYS, age_days + _DELTA_OVERLAP_DAYS)


def _cached_market_loader(
    candidate: MarketHistoryCandidate,
    *,
    as_of: datetime,
    minimum_rows: int,
    store: PersistentHistoricalEvidenceStore,
):
    original_loader = candidate.loader
    asset_class = _asset_class_from_capability(candidate.capability)
    provider_scope = candidate.key.identifier

    def load():
        cached = store.load(
            asset_class=asset_class,
            instrument_identity=candidate.instrument_identity,
            provider_scope=provider_scope,
            as_of=as_of,
        )
        if len(cached.rows) >= minimum_rows and _is_recent(
            cached,
            as_of=as_of,
            max_age_hours=store.max_age_hours,
        ):
            return cached.rows
        fetched = original_loader()
        if not isinstance(fetched, Sequence) or isinstance(fetched, (str, bytes)):
            return fetched
        mappings = tuple(item for item in fetched if isinstance(item, Mapping))
        if not mappings:
            return fetched
        merged = store.merge(
            asset_class=asset_class,
            instrument_identity=candidate.instrument_identity,
            provider_scope=provider_scope,
            rows=mappings,
            requested_as_of=as_of,
        )
        return merged.rows

    return load


def _option_rows_to_mappings(rows: Sequence[object]) -> tuple[dict[str, object], ...]:
    material: list[dict[str, object]] = []
    for item in rows:
        observed = getattr(item, "observed_at", None)
        if not isinstance(observed, datetime):
            continue
        material.append(
            {
                "t": observed,
                "c": float(getattr(item, "close")),
                "v": float(getattr(item, "volume", 0.0)),
                "provider_kind": str(getattr(item, "provider_kind", "")),
                "source_identifier": str(getattr(item, "source_identifier", "")),
            }
        )
    return tuple(material)


def _option_rows_from_mappings(raw_symbol: str, rows: Sequence[Mapping[str, object]]):
    from providers.redundant_options import RedundantOptionBar

    return tuple(
        RedundantOptionBar(
            raw_symbol=raw_symbol,
            observed_at=_aware(item["t"]),  # type: ignore[arg-type]
            close=float(item["c"]),
            volume=float(item.get("v", 0.0)),
            provider_kind=str(item.get("provider_kind") or "persistent_history"),
            source_identifier=str(
                item.get("source_identifier")
                or f"persistent-option-history:{raw_symbol}:{_aware(item['t']).isoformat()}"  # type: ignore[arg-type]
            ),
        )
        for item in rows
    )


def install_persistent_historical_evidence() -> None:
    """Install idempotent persistent-history wrappers at both production boundaries."""

    current_market_fetch = RedundantMarketHistoryRouter.fetch
    if not bool(getattr(current_market_fetch, "persistent_historical_evidence", False)):

        def persistent_market_fetch(self, candidates, *, as_of, minimum_rows):
            store = PersistentHistoricalEvidenceStore()
            if not store.enabled:
                return current_market_fetch(
                    self,
                    candidates,
                    as_of=as_of,
                    minimum_rows=minimum_rows,
                )
            wrapped = tuple(
                replace(
                    candidate,
                    loader=_cached_market_loader(
                        candidate,
                        as_of=_aware(as_of),
                        minimum_rows=minimum_rows,
                        store=store,
                    ),
                )
                for candidate in candidates
            )
            return current_market_fetch(
                self,
                wrapped,
                as_of=as_of,
                minimum_rows=minimum_rows,
            )

        persistent_market_fetch.persistent_historical_evidence = True
        RedundantMarketHistoryRouter.fetch = persistent_market_fetch

    from operations.resumable_options_discovery import ResumableOptionsProvider

    current_option_history = ResumableOptionsProvider._resilient_history
    if bool(getattr(current_option_history, "persistent_historical_evidence", False)):
        return

    def persistent_option_history(self, raw_symbols, *, as_of, history_days):
        store = PersistentHistoricalEvidenceStore(self._values)
        if not store.enabled:
            return current_option_history(
                self,
                raw_symbols,
                as_of=as_of,
                history_days=history_days,
            )
        timestamp = _aware(as_of)
        symbols = tuple(
            dict.fromkeys(
                str(item).strip().upper()
                for item in raw_symbols
                if str(item).strip()
            )
        )
        if not symbols:
            return {}

        result: dict[str, tuple[object, ...]] = {}
        refresh: dict[str, HistoricalEvidenceSlice] = {}
        full: list[str] = []
        for symbol in symbols:
            cached = store.load(
                asset_class="option",
                instrument_identity=symbol,
                provider_scope="exact_option_history",
                as_of=timestamp,
            )
            if cached.maximum_history_days < int(history_days):
                full.append(symbol)
                continue
            if _is_recent(
                cached,
                as_of=timestamp,
                max_age_hours=store.max_age_hours,
            ):
                if cached.rows:
                    result[symbol] = _option_rows_from_mappings(symbol, cached.rows)
                continue
            refresh[symbol] = cached

        if full:
            fetched = current_option_history(
                self,
                tuple(full),
                as_of=timestamp,
                history_days=history_days,
            )
            for symbol in full:
                bars = tuple(fetched.get(symbol, ()))
                if not bars:
                    continue
                merged = store.merge(
                    asset_class="option",
                    instrument_identity=symbol,
                    provider_scope="exact_option_history",
                    rows=_option_rows_to_mappings(bars),
                    requested_as_of=timestamp,
                    requested_history_days=int(history_days),
                )
                result[symbol] = _option_rows_from_mappings(symbol, merged.rows)

        if refresh:
            delta_days = max(
                _delta_history_days(item, as_of=timestamp)
                for item in refresh.values()
            )
            delta_days = min(max(1, int(history_days)), delta_days)
            fetched = current_option_history(
                self,
                tuple(refresh),
                as_of=timestamp,
                history_days=delta_days,
            )
            for symbol, cached in refresh.items():
                bars = tuple(fetched.get(symbol, ()))
                if not bars:
                    # Do not certify a stale cache when the required decision-time
                    # refresh could not be obtained.
                    continue
                merged = store.merge(
                    asset_class="option",
                    instrument_identity=symbol,
                    provider_scope="exact_option_history",
                    rows=_option_rows_to_mappings(bars),
                    requested_as_of=timestamp,
                    requested_history_days=cached.maximum_history_days,
                )
                result[symbol] = _option_rows_from_mappings(symbol, merged.rows)

        return {symbol: result[symbol] for symbol in symbols if symbol in result}

    persistent_option_history.persistent_historical_evidence = True
    ResumableOptionsProvider._resilient_history = persistent_option_history


__all__ = [
    "HistoricalEvidenceSlice",
    "PersistentHistoricalEvidenceError",
    "PersistentHistoricalEvidenceStore",
    "install_persistent_historical_evidence",
]
