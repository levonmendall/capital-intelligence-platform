"""Persistent point-in-time historical evidence shared by all executable asset lanes.

The store keeps already-observed daily history on the persistent service disk so a new
CIO decision epoch does not have to redownload immutable history.  Reuse never grants
freshness by itself: each cached scope records the request boundary that last refreshed
it, and callers must refresh an overdue tail before the cache can satisfy a new epoch.

The module installs two operational wrappers:

* every non-option exact-instrument market-history candidate routed through
  ``RedundantMarketHistoryRouter`` can reuse a recently refreshed persistent base; and
* resumable options preserve the largest previously requested history horizon and, once
  that horizon exists, refresh only a small overlapping tail instead of repeating a
  365-day pull for every decision epoch.

Rows are keyed by asset class, exact economic-instrument identity, provider scope, and
observation timestamp.  Row payloads carry an integrity digest, future-dated writes are
rejected, and the SQLite database uses bounded transactions.  Current quotes, spreads,
liquidity, IV/Greeks, fundamentals, specialist analysis, CIO authority, construction,
and execution remain outside this cache and must satisfy their existing decision-time
freshness and governance contracts.
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
    """Small SQLite-backed append/replace store for immutable daily evidence bases."""

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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_evidence_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
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
        # Keep the original table for an in-place, non-destructive migration and for
        # compatibility with already-deployed databases. New reads use the append-only
        # epoch table below so a newer refresh cannot overwrite an older CIO epoch's
        # coverage metadata.
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
            CREATE TABLE IF NOT EXISTS historical_evidence_coverage_epochs (
                asset_class TEXT NOT NULL,
                instrument_identity TEXT NOT NULL,
                provider_scope TEXT NOT NULL,
                maximum_history_days INTEGER NOT NULL,
                requested_as_of TEXT NOT NULL,
                integrity_sha256 TEXT NOT NULL,
                PRIMARY KEY (
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    requested_as_of
                )
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_evidence_row_epochs (
                asset_class TEXT NOT NULL,
                instrument_identity TEXT NOT NULL,
                provider_scope TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                requested_as_of TEXT NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                provider_kind TEXT NOT NULL,
                source_identifier TEXT NOT NULL,
                integrity_sha256 TEXT NOT NULL,
                PRIMARY KEY (
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    observed_at,
                    requested_as_of
                )
            )
            """
        )
        # Preserve the last pre-upgrade coverage row as the first known epoch. This is
        # idempotent and does not mutate or discard existing coverage.
        connection.execute(
            """
            INSERT OR IGNORE INTO historical_evidence_coverage_epochs(
                asset_class, instrument_identity, provider_scope,
                maximum_history_days, requested_as_of, integrity_sha256
            )
            SELECT asset_class, instrument_identity, provider_scope,
                   maximum_history_days, requested_as_of, integrity_sha256
            FROM historical_evidence_coverage
            """
        )
        # Legacy rows predate explicit row-ingest epochs. Attribute them only to the
        # latest trusted legacy coverage epoch for their scope. Earlier decision epochs
        # remain fail-closed rather than inheriting data recorded later.
        connection.execute(
            """
            INSERT OR IGNORE INTO historical_evidence_row_epochs(
                asset_class, instrument_identity, provider_scope, observed_at,
                requested_as_of, close, volume, provider_kind, source_identifier,
                integrity_sha256
            )
            SELECT rows.asset_class, rows.instrument_identity, rows.provider_scope,
                   rows.observed_at, coverage.requested_as_of, rows.close, rows.volume,
                   rows.provider_kind, rows.source_identifier, rows.integrity_sha256
            FROM historical_evidence_rows AS rows
            JOIN historical_evidence_coverage AS coverage
              ON coverage.asset_class=rows.asset_class
             AND coverage.instrument_identity=rows.instrument_identity
             AND coverage.provider_scope=rows.provider_scope
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
        connection.commit()
        return connection

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
            rows = connection.execute(
                """
                SELECT candidate.observed_at, candidate.close, candidate.volume,
                       candidate.provider_kind, candidate.source_identifier,
                       candidate.integrity_sha256
                FROM historical_evidence_row_epochs AS candidate
                WHERE candidate.asset_class=?
                  AND candidate.instrument_identity=?
                  AND candidate.provider_scope=?
                  AND candidate.requested_as_of<=?
                  AND candidate.observed_at<=?
                  AND candidate.requested_as_of=(
                      SELECT MAX(version.requested_as_of)
                      FROM historical_evidence_row_epochs AS version
                      WHERE version.asset_class=candidate.asset_class
                        AND version.instrument_identity=candidate.instrument_identity
                        AND version.provider_scope=candidate.provider_scope
                        AND version.observed_at=candidate.observed_at
                        AND version.requested_as_of<=?
                  )
                ORDER BY candidate.observed_at
                """,
                (
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            ).fetchall()
            material: list[dict[str, object]] = []
            for observed_raw, close, volume, provider_kind, source_identifier, integrity in rows:
                payload = {
                    "asset_class": asset_class,
                    "instrument_identity": instrument_identity,
                    "provider_scope": provider_scope,
                    "observed_at": observed_raw,
                    "close": float(close),
                    "volume": float(volume),
                    "provider_kind": str(provider_kind),
                    "source_identifier": str(source_identifier),
                }
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

            coverage = connection.execute(
                """
                SELECT maximum_history_days, requested_as_of, integrity_sha256
                FROM historical_evidence_coverage_epochs
                WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
                  AND requested_as_of<=?
                ORDER BY requested_as_of DESC
                LIMIT 1
                """,
                (
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    timestamp.isoformat(),
                ),
            ).fetchone()
            if coverage is None:
                future_coverage = connection.execute(
                    """
                    SELECT 1
                    FROM historical_evidence_coverage_epochs
                    WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
                      AND requested_as_of>?
                    LIMIT 1
                    """,
                    (
                        asset_class,
                        instrument_identity,
                        provider_scope,
                        timestamp.isoformat(),
                    ),
                ).fetchone()
                if future_coverage is not None:
                    raise PersistentHistoricalEvidenceError(
                        "persistent historical evidence was refreshed after the decision epoch"
                    )
                return HistoricalEvidenceSlice(tuple(material), 0, None)

            maximum_days, requested_raw, integrity = coverage
            payload = {
                "asset_class": asset_class,
                "instrument_identity": instrument_identity,
                "provider_scope": provider_scope,
                "maximum_history_days": int(maximum_days),
                "requested_as_of": str(requested_raw),
            }
            if integrity != _digest(payload):
                raise PersistentHistoricalEvidenceError(
                    "persistent historical evidence coverage integrity mismatch"
                )
            requested = _aware(datetime.fromisoformat(str(requested_raw)))
            if requested > timestamp:
                raise PersistentHistoricalEvidenceError(
                    "persistent historical evidence was refreshed after the decision epoch"
                )
            return HistoricalEvidenceSlice(tuple(material), int(maximum_days), requested)
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
            return HistoricalEvidenceSlice(normalized, max(0, requested_history_days), _aware(requested_as_of))
        timestamp = _aware(requested_as_of)
        normalized = _normalize_mapping_rows(rows, as_of=timestamp)
        connection = self._connect()
        try:
            with connection:
                for item in normalized:
                    observed = _aware(item["t"])  # type: ignore[arg-type]
                    provider_kind = str(item.get("provider_kind") or "")
                    source_identifier = str(item.get("source_identifier") or "")
                    payload = {
                        "asset_class": asset_class,
                        "instrument_identity": instrument_identity,
                        "provider_scope": provider_scope,
                        "observed_at": observed.isoformat(),
                        "close": float(item["c"]),
                        "volume": float(item.get("v", 0.0)),
                        "provider_kind": provider_kind,
                        "source_identifier": source_identifier,
                    }
                    row_values = (
                        asset_class,
                        instrument_identity,
                        provider_scope,
                        observed.isoformat(),
                        float(item["c"]),
                        float(item.get("v", 0.0)),
                        provider_kind,
                        source_identifier,
                        _digest(payload),
                    )
                    connection.execute(
                        """
                        INSERT INTO historical_evidence_row_epochs(
                            asset_class, instrument_identity, provider_scope, observed_at,
                            requested_as_of, close, volume, provider_kind, source_identifier,
                            integrity_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(
                            asset_class, instrument_identity, provider_scope,
                            observed_at, requested_as_of
                        ) DO UPDATE SET close=excluded.close, volume=excluded.volume,
                                        provider_kind=excluded.provider_kind,
                                        source_identifier=excluded.source_identifier,
                                        integrity_sha256=excluded.integrity_sha256
                        """,
                        (
                            asset_class,
                            instrument_identity,
                            provider_scope,
                            observed.isoformat(),
                            timestamp.isoformat(),
                            float(item["c"]),
                            float(item.get("v", 0.0)),
                            provider_kind,
                            source_identifier,
                            _digest(payload),
                        ),
                    )
                    # Maintain the legacy latest-row table for rollback compatibility.
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
                        row_values,
                    )

                existing = connection.execute(
                    """
                    SELECT MAX(maximum_history_days)
                    FROM historical_evidence_coverage_epochs
                    WHERE asset_class=? AND instrument_identity=? AND provider_scope=?
                      AND requested_as_of<=?
                    """,
                    (
                        asset_class,
                        instrument_identity,
                        provider_scope,
                        timestamp.isoformat(),
                    ),
                ).fetchone()
                maximum_days = max(
                    int(existing[0]) if existing is not None and existing[0] is not None else 0,
                    max(0, int(requested_history_days)),
                )
                coverage_payload = {
                    "asset_class": asset_class,
                    "instrument_identity": instrument_identity,
                    "provider_scope": provider_scope,
                    "maximum_history_days": maximum_days,
                    "requested_as_of": timestamp.isoformat(),
                }
                coverage_values = (
                    asset_class,
                    instrument_identity,
                    provider_scope,
                    maximum_days,
                    timestamp.isoformat(),
                    _digest(coverage_payload),
                )
                connection.execute(
                    """
                    INSERT INTO historical_evidence_coverage_epochs(
                        asset_class, instrument_identity, provider_scope,
                        maximum_history_days, requested_as_of, integrity_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_class, instrument_identity, provider_scope, requested_as_of)
                    DO UPDATE SET maximum_history_days=excluded.maximum_history_days,
                                  integrity_sha256=excluded.integrity_sha256
                    """,
                    coverage_values,
                )
                # Maintain the legacy latest-row table for compatibility with deployed
                # databases and rollback safety. Point-in-time reads never depend on it.
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
                    WHERE excluded.requested_as_of >= historical_evidence_coverage.requested_as_of
                    """,
                    coverage_values,
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
