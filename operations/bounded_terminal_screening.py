"""Bound terminal all-market screening without changing admission semantics.

The canonical provider-factor publication is intentionally a complete JSON audit
artifact. Loading that artifact together with a complete certified catalog, baseline
signals, enriched signals, and a second validation mapping can create several complete
in-memory representations of a large market lane. This module keeps the publication
unchanged on disk, streams its signal members into a temporary SQLite spool, and
persists completed terminal-screening state to a second SQLite spool.

Only one fixed-size signal chunk is retained in Python while screening. Complete
point-in-time results, exclusions, factor scores, prices, timestamps, and evidence
lineage are persisted before the chunk is released. Global sleeve ranking and
nomination are performed only after the complete lane has been screened, preserving
the existing all-market comparison semantics. No market, factor, evidence, liquidity,
freshness, ranking, threshold, or authority rule is changed.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Mapping, Sequence

from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress
from operations.market_discovery_preselection import (
    CandidateSleeve,
    CutoffObservation,
    PreselectionPlan,
    SLEEVES,
    _aware,
    _bucket,
    _tie,
)
from operations.provider_enriched_preselection import (
    PROVIDER_PRESELECTION_SCHEMA,
    provider_enriched_catalog_screening_signals,
    validate_provider_enriched_signals,
)


DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE = 512
_SQLITE_CACHE_KIB = 2048
_TOP_LEVEL_KEY = re.compile(r'^  (?P<key>"(?:\\.|[^"\\])+"): (?P<value>.*)$')
_SIGNAL_KEY = re.compile(r'^    (?P<key>"(?:\\.|[^"\\])+"): (?P<value>\{.*)$')
_SCORE_COLUMNS = {
    CandidateSleeve.QUALITY: ("quality_score", "quality_tie"),
    CandidateSleeve.VALUE: ("value_score", "value_tie"),
    CandidateSleeve.MOMENTUM: ("momentum_score", "momentum_tie"),
    CandidateSleeve.CARRY: ("carry_score", "carry_tie"),
    CandidateSleeve.DIVERSIFICATION: (
        "diversification_score",
        "diversification_tie",
    ),
    CandidateSleeve.IMPROVING_CONDITIONS: (
        "improving_conditions_score",
        "improving_conditions_tie",
    ),
}


class BoundedTerminalScreeningError(RuntimeError):
    """Raised when the canonical publication cannot be streamed safely."""


@dataclass(frozen=True, slots=True)
class BoundedTerminalPreselection:
    plan: PreselectionPlan
    nominated: tuple[object, ...]
    signal_prices: Mapping[str, float]
    signal_observed_at: Mapping[str, datetime]
    preselection_evidence: tuple[tuple[str, tuple[str, ...]], ...]
    provider_factor_authority_established: bool
    publication_failure_reasons: tuple[str, ...]
    screened_signal_count: int


def _advise_file_cache_dontneed(path: Path) -> None:
    """Best-effort release of file-backed cache without changing durable contents."""

    posix_fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    if posix_fadvise is None or advice is None or not path.exists():
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            posix_fadvise(descriptor, 0, 0, advice)
        except OSError:
            pass
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _configure_spool_connection(connection: sqlite3.Connection) -> None:
    """Keep SQLite working memory bounded for production diagnostic spools."""

    connection.execute("PRAGMA temp_store = FILE")
    connection.execute(f"PRAGMA cache_size = -{_SQLITE_CACHE_KIB}")
    connection.execute("PRAGMA mmap_size = 0")


class _PublicationSignalSpool:
    """Stream one canonical pretty-JSON publication into a disk-backed signal index."""

    __slots__ = (
        "publication_path",
        "_temporary",
        "database_path",
        "connection",
        "metadata",
        "signal_count",
    )

    def __init__(self, publication_path: Path) -> None:
        self.publication_path = publication_path
        self._temporary = tempfile.TemporaryDirectory(prefix="cio-terminal-screening-")
        self.database_path = Path(self._temporary.name) / "signals.sqlite3"
        self.connection = sqlite3.connect(self.database_path)
        _configure_spool_connection(self.connection)
        self.connection.execute(
            "CREATE TABLE signals (symbol TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.metadata: dict[str, object] = {}
        self.signal_count = 0
        self._stream_publication()

    def close(self) -> None:
        try:
            self.connection.close()
        finally:
            self._temporary.cleanup()

    def __enter__(self) -> "_PublicationSignalSpool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _decode_value(text: str) -> tuple[object, int] | None:
        try:
            return json.JSONDecoder().raw_decode(text.lstrip())
        except json.JSONDecodeError:
            return None

    def _stream_publication(self) -> None:
        if not self.publication_path.exists():
            raise BoundedTerminalScreeningError(
                f"provider preselection publication is unavailable at {self.publication_path}"
            )
        mode = "top"
        pending_key: str | None = None
        pending_value = ""
        signal_symbol: str | None = None
        signal_value = ""
        saw_signals = False
        try:
            handle = self.publication_path.open("r", encoding="utf-8")
        except OSError as error:
            raise BoundedTerminalScreeningError(
                "provider preselection publication cannot be opened"
            ) from error
        with handle:
            for line in handle:
                if mode == "signals":
                    if signal_symbol is not None:
                        signal_value += line
                        decoded = self._decode_value(signal_value)
                        if decoded is not None:
                            value, _end = decoded
                            if not isinstance(value, Mapping):
                                raise BoundedTerminalScreeningError(
                                    "provider publication signal must be a JSON object"
                                )
                            self.connection.execute(
                                "INSERT INTO signals(symbol, payload) VALUES (?, ?)",
                                (
                                    signal_symbol,
                                    json.dumps(
                                        dict(value),
                                        sort_keys=True,
                                        separators=(",", ":"),
                                        allow_nan=False,
                                    ),
                                ),
                            )
                            self.signal_count += 1
                            signal_symbol = None
                            signal_value = ""
                        continue
                    if line.startswith("  }"):
                        mode = "top"
                        continue
                    match = _SIGNAL_KEY.match(line.rstrip("\n"))
                    if match is None:
                        if not line.strip():
                            continue
                        raise BoundedTerminalScreeningError(
                            "provider publication signals are not in canonical streamed form"
                        )
                    signal_symbol = str(json.loads(match.group("key"))).strip().upper()
                    if not signal_symbol:
                        raise BoundedTerminalScreeningError(
                            "provider publication contains an empty signal symbol"
                        )
                    signal_value = match.group("value") + "\n"
                    decoded = self._decode_value(signal_value)
                    if decoded is not None:
                        value, _end = decoded
                        if not isinstance(value, Mapping):
                            raise BoundedTerminalScreeningError(
                                "provider publication signal must be a JSON object"
                            )
                        self.connection.execute(
                            "INSERT INTO signals(symbol, payload) VALUES (?, ?)",
                            (
                                signal_symbol,
                                json.dumps(
                                    dict(value),
                                    sort_keys=True,
                                    separators=(",", ":"),
                                    allow_nan=False,
                                ),
                            ),
                        )
                        self.signal_count += 1
                        signal_symbol = None
                        signal_value = ""
                    continue

                if pending_key is not None:
                    pending_value += line
                    decoded = self._decode_value(pending_value)
                    if decoded is not None:
                        value, _end = decoded
                        self.metadata[pending_key] = value
                        pending_key = None
                        pending_value = ""
                    continue

                match = _TOP_LEVEL_KEY.match(line.rstrip("\n"))
                if match is None:
                    continue
                key = str(json.loads(match.group("key")))
                value_text = match.group("value") + "\n"
                if key == "signals":
                    if not value_text.lstrip().startswith("{"):
                        raise BoundedTerminalScreeningError(
                            "provider publication signals must be a JSON object"
                        )
                    mode = "signals"
                    saw_signals = True
                    continue
                decoded = self._decode_value(value_text)
                if decoded is not None:
                    value, _end = decoded
                    self.metadata[key] = value
                else:
                    pending_key = key
                    pending_value = value_text
        if mode == "signals" or signal_symbol is not None or pending_key is not None:
            raise BoundedTerminalScreeningError(
                "provider preselection publication ended before a JSON value completed"
            )
        if not saw_signals:
            raise BoundedTerminalScreeningError(
                "provider preselection publication does not contain signals"
            )
        if self.metadata.get("schema_version") != PROVIDER_PRESELECTION_SCHEMA:
            raise BoundedTerminalScreeningError(
                "unsupported provider preselection schema"
            )
        if "available_at" not in self.metadata:
            raise BoundedTerminalScreeningError(
                "provider preselection publication available_at is missing"
            )
        self.connection.commit()
        _advise_file_cache_dontneed(self.publication_path)
        self.release_cached_pages()

    def release_cached_pages(self) -> None:
        _advise_file_cache_dontneed(self.database_path)

    def signals_for(self, records: Sequence[object]) -> dict[str, object]:
        result: dict[str, object] = {}
        cursor = self.connection.cursor()
        for record in records:
            symbol = str(getattr(record, "symbol", "")).strip().upper()
            provider_symbol = str(
                getattr(record, "provider_symbol", symbol)
            ).strip().upper()
            row = cursor.execute(
                "SELECT payload FROM signals WHERE symbol = ?", (symbol,)
            ).fetchone()
            if row is None and provider_symbol and provider_symbol != symbol:
                row = cursor.execute(
                    "SELECT payload FROM signals WHERE symbol = ?", (provider_symbol,)
                ).fetchone()
            if row is None:
                continue
            result[symbol] = json.loads(str(row[0]))
        return result

    def chunk_publication(self, records: Sequence[object], target: Path) -> None:
        payload = {
            "schema_version": self.metadata["schema_version"],
            "available_at": self.metadata["available_at"],
            "source_identifiers": self.metadata.get("source_identifiers", ()),
            "signals": self.signals_for(records),
        }
        target.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


class _TerminalScreeningStateSpool:
    """Persist completed screening state so chunk results do not accumulate in RAM."""

    __slots__ = ("_temporary", "database_path", "connection")

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="cio-terminal-state-")
        self.database_path = Path(self._temporary.name) / "screening.sqlite3"
        self.connection = sqlite3.connect(self.database_path)
        _configure_spool_connection(self.connection)
        self.connection.executescript(
            """
            CREATE TABLE screened (
                ordinal INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                eligible INTEGER NOT NULL,
                bucket_exposure TEXT NOT NULL,
                bucket_venue TEXT NOT NULL,
                bucket_country TEXT NOT NULL,
                bucket_currency TEXT NOT NULL,
                observed_at TEXT,
                indicative_price REAL,
                evidence_json TEXT,
                quality_score REAL,
                quality_tie REAL,
                value_score REAL,
                value_tie REAL,
                momentum_score REAL,
                momentum_tie REAL,
                carry_score REAL,
                carry_tie REAL,
                diversification_score REAL,
                diversification_tie REAL,
                improving_conditions_score REAL,
                improving_conditions_tie REAL
            );
            CREATE INDEX screened_symbol_idx ON screened(symbol);
            CREATE TABLE exclusions (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        try:
            self.connection.close()
        finally:
            self._temporary.cleanup()

    def __enter__(self) -> "_TerminalScreeningStateSpool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def append(
        self,
        *,
        ordinal: int,
        record: object,
        signal: object | None,
        reasons: Sequence[str],
        as_of: datetime,
    ) -> None:
        symbol = str(getattr(record, "symbol", "")).strip().upper()
        bucket = tuple(str(item) for item in _bucket(record))
        accepted = signal is not None and not reasons
        observed_at = None
        indicative_price = None
        evidence_json = None
        values: dict[CandidateSleeve, float | None] = {
            CandidateSleeve.QUALITY: None,
            CandidateSleeve.VALUE: None,
            CandidateSleeve.MOMENTUM: None,
            CandidateSleeve.CARRY: None,
            CandidateSleeve.IMPROVING_CONDITIONS: None,
        }
        if signal is not None:
            observed_at = signal.observed_at.isoformat() if accepted else None
            indicative_price = (
                None
                if signal.indicative_price is None
                else float(signal.indicative_price)
            )
            if accepted:
                evidence_json = json.dumps(
                    tuple(signal.evidence_identifiers),
                    separators=(",", ":"),
                    allow_nan=False,
                )
                values = {
                    CandidateSleeve.QUALITY: signal.quality_score,
                    CandidateSleeve.VALUE: signal.value_score,
                    CandidateSleeve.MOMENTUM: signal.momentum_score,
                    CandidateSleeve.CARRY: signal.carry_score,
                    CandidateSleeve.IMPROVING_CONDITIONS: (
                        signal.improving_conditions_score
                    ),
                }

        ties = {sleeve: _tie(as_of, sleeve, symbol) for sleeve in SLEEVES}
        self.connection.execute(
            """
            INSERT INTO screened(
                ordinal, symbol, eligible,
                bucket_exposure, bucket_venue, bucket_country, bucket_currency,
                observed_at, indicative_price, evidence_json,
                quality_score, quality_tie,
                value_score, value_tie,
                momentum_score, momentum_tie,
                carry_score, carry_tie,
                diversification_score, diversification_tie,
                improving_conditions_score, improving_conditions_tie
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                NULL, ?,
                ?, ?
            )
            """,
            (
                ordinal,
                symbol,
                1 if accepted else 0,
                *bucket,
                observed_at,
                indicative_price,
                evidence_json,
                None
                if values[CandidateSleeve.QUALITY] is None
                else float(values[CandidateSleeve.QUALITY]),
                ties[CandidateSleeve.QUALITY],
                None
                if values[CandidateSleeve.VALUE] is None
                else float(values[CandidateSleeve.VALUE]),
                ties[CandidateSleeve.VALUE],
                None
                if values[CandidateSleeve.MOMENTUM] is None
                else float(values[CandidateSleeve.MOMENTUM]),
                ties[CandidateSleeve.MOMENTUM],
                None
                if values[CandidateSleeve.CARRY] is None
                else float(values[CandidateSleeve.CARRY]),
                ties[CandidateSleeve.CARRY],
                ties[CandidateSleeve.DIVERSIFICATION],
                None
                if values[CandidateSleeve.IMPROVING_CONDITIONS] is None
                else float(values[CandidateSleeve.IMPROVING_CONDITIONS]),
                ties[CandidateSleeve.IMPROVING_CONDITIONS],
            ),
        )
        if reasons:
            self.connection.executemany(
                "INSERT INTO exclusions(symbol, reason) VALUES (?, ?)",
                ((symbol, str(reason)) for reason in reasons),
            )

    def release_cached_pages(self) -> None:
        _advise_file_cache_dontneed(self.database_path)

    def commit_chunk(self) -> None:
        self.connection.commit()
        self.release_cached_pages()

    def finalize_diversification(self, *, batch_size: int = 512) -> None:
        cursor = self.connection.execute(
            """
            SELECT
                item.ordinal,
                1.0 / bucket_counts.member_count AS diversification_score
            FROM screened AS item
            JOIN (
                SELECT
                    bucket_exposure,
                    bucket_venue,
                    bucket_country,
                    bucket_currency,
                    COUNT(*) AS member_count
                FROM screened
                WHERE eligible = 1
                GROUP BY
                    bucket_exposure,
                    bucket_venue,
                    bucket_country,
                    bucket_currency
            ) AS bucket_counts
              ON bucket_counts.bucket_exposure = item.bucket_exposure
             AND bucket_counts.bucket_venue = item.bucket_venue
             AND bucket_counts.bucket_country = item.bucket_country
             AND bucket_counts.bucket_currency = item.bucket_currency
            WHERE item.eligible = 1
            ORDER BY item.ordinal
            """
        )
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            self.connection.executemany(
                "UPDATE screened SET diversification_score = ? WHERE ordinal = ?",
                ((float(score), int(ordinal)) for ordinal, score in rows),
            )
        self.connection.commit()

    @property
    def eligible_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM screened WHERE eligible = 1"
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def ranking(self, sleeve: CandidateSleeve) -> tuple[str, ...]:
        score_column, tie_column = _SCORE_COLUMNS[sleeve]
        query = (
            "SELECT symbol FROM screened "
            f"WHERE eligible = 1 AND {score_column} IS NOT NULL "
            f"ORDER BY {score_column} DESC, {tie_column} DESC, symbol DESC"
        )
        return tuple(str(row[0]) for row in self.connection.execute(query))

    def factor_coverage(self) -> tuple[tuple[str, int], ...]:
        result = []
        for sleeve in SLEEVES:
            score_column, _tie_column = _SCORE_COLUMNS[sleeve]
            row = self.connection.execute(
                f"SELECT COUNT({score_column}) FROM screened WHERE eligible = 1"
            ).fetchone()
            result.append((sleeve.value, int(row[0]) if row is not None else 0))
        return tuple(result)

    def exclusions(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (str(symbol), str(reason))
            for symbol, reason in self.connection.execute(
                "SELECT symbol, reason FROM exclusions ORDER BY sequence"
            )
        )

    def prepare_measured(self, measured: Sequence[str]) -> None:
        self.connection.execute("DROP TABLE IF EXISTS measured_order")
        self.connection.execute(
            "CREATE TEMP TABLE measured_order("
            "position INTEGER PRIMARY KEY, symbol TEXT NOT NULL)"
        )
        self.connection.executemany(
            "INSERT INTO measured_order(position, symbol) VALUES (?, ?)",
            ((index, symbol) for index, symbol in enumerate(measured)),
        )

    def measured_rows(self):
        return self.connection.execute(
            """
            SELECT
                measured_order.position,
                screened.ordinal,
                screened.quality_score,
                screened.value_score,
                screened.momentum_score,
                screened.carry_score,
                screened.diversification_score,
                screened.improving_conditions_score,
                screened.observed_at,
                screened.indicative_price,
                screened.evidence_json
            FROM measured_order
            JOIN screened ON screened.symbol = measured_order.symbol
            ORDER BY measured_order.position
            """
        )

    def signal_prices(self) -> dict[str, float]:
        return {
            str(symbol): float(price)
            for symbol, price in self.connection.execute(
                """
                SELECT symbol, indicative_price
                FROM screened
                WHERE indicative_price IS NOT NULL
                ORDER BY ordinal
                """
            )
        }


def _chunks(values: Sequence[object], size: int):
    for start in range(0, len(values), size):
        yield start, values[start : start + size]


def build_bounded_terminal_preselection(
    records: Sequence[object],
    *,
    as_of: datetime,
    policy: object,
    progress_label: str,
    chunk_size: int = DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE,
) -> BoundedTerminalPreselection:
    """Reproduce complete-consideration preselection with disk-backed retained state."""

    timestamp = _aware(as_of)
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    publication_path = Path(str(getattr(policy, "provider_preselection_path"))).expanduser()
    publication_failures: set[str] = set()
    substantive_provider_factor = False
    screened_signal_count = 0

    with _PublicationSignalSpool(publication_path) as publication_spool:
        with _TerminalScreeningStateSpool() as state_spool:
            with tempfile.TemporaryDirectory(prefix="cio-terminal-chunks-") as temporary:
                chunk_path = Path(temporary) / "provider-preselection-chunk.json"
                processed = 0
                for start, chunk in _chunks(records, chunk_size):
                    publication_spool.chunk_publication(chunk, chunk_path)
                    chunk_policy = replace(
                        policy,
                        provider_preselection_path=str(chunk_path),
                    )
                    signals = provider_enriched_catalog_screening_signals(
                        chunk,
                        timestamp,
                        chunk_policy,
                    )
                    if not isinstance(signals, Mapping):
                        raise BoundedTerminalScreeningError(
                            "provider-enriched screening chunk did not return a mapping"
                        )
                    signals = validate_provider_enriched_signals(
                        chunk,
                        signals,
                        required_factors=getattr(
                            policy,
                            "required_provider_preselection_factors",
                        ),
                    )
                    normalized_signals = {
                        str(symbol).strip().upper(): signal
                        for symbol, signal in signals.items()
                    }
                    screened_signal_count += len(normalized_signals)
                    freshness_days = int(
                        getattr(policy, "preselection_freshness_days", 3)
                    )
                    minimum_liquidity = float(
                        getattr(policy, "preselection_minimum_liquidity_score", 0.0)
                    )
                    for offset, record in enumerate(chunk):
                        symbol = str(getattr(record, "symbol", "")).strip().upper()
                        signal = normalized_signals.get(symbol)
                        if signal is None:
                            state_spool.append(
                                ordinal=start + offset,
                                record=record,
                                signal=None,
                                reasons=("catalog_screening_signal_unavailable",),
                                as_of=timestamp,
                            )
                            continue

                        substantive_provider_factor = substantive_provider_factor or any(
                            identifier.startswith("provider-factor:")
                            for identifier in signal.evidence_identifiers
                        )
                        publication_failures.update(
                            reason
                            for reason in signal.exclusion_reasons
                            if reason.startswith(
                                "provider_enriched_preselection_publication_invalid:"
                            )
                        )
                        reasons = list(signal.exclusion_reasons)
                        age_seconds = (timestamp - signal.observed_at).total_seconds()
                        if age_seconds < 0 or age_seconds > freshness_days * 86_400:
                            reasons.append("catalog_screening_signal_stale")
                        if signal.liquidity_score is None:
                            reasons.append("catalog_basic_liquidity_unavailable")
                        elif signal.liquidity_score < minimum_liquidity:
                            reasons.append("catalog_basic_liquidity_failed")
                        if not signal.eligible:
                            reasons.append("catalog_ineligible")
                        state_spool.append(
                            ordinal=start + offset,
                            record=record,
                            signal=signal,
                            reasons=tuple(dict.fromkeys(reasons)),
                            as_of=timestamp,
                        )

                    state_spool.commit_chunk()
                    processed += len(chunk)
                    del normalized_signals
                    del signals
                    _advise_file_cache_dontneed(chunk_path)
                    publication_spool.release_cached_pages()
                    state_spool.release_cached_pages()
                    record_manual_cio_diagnostic_progress(
                        f"terminal_screening_chunk:{progress_label}",
                        metrics={
                            "processed_records": processed,
                            "total_records": len(records),
                            "chunk_records": len(chunk),
                        },
                    )

            authority_established = not records or substantive_provider_factor
            if not authority_established:
                detail = (
                    "; " + ", ".join(sorted(publication_failures))
                    if publication_failures
                    else ""
                )
                raise BoundedTerminalScreeningError(
                    f"{progress_label} provider factor authority is unavailable for the "
                    f"complete certified catalog{detail}"
                )

            state_spool.finalize_diversification(
                batch_size=min(chunk_size, DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE)
            )
            rankings = {
                sleeve: state_spool.ranking(sleeve)
                for sleeve in SLEEVES
            }
            eligible_count = state_spool.eligible_count
            capacity = max(1, len(records))
            selected: list[str] = []
            seen: set[str] = set()
            cursors = {sleeve: 0 for sleeve in SLEEVES}
            while len(selected) < min(capacity, eligible_count):
                progressed = False
                for sleeve in SLEEVES:
                    ranking = rankings[sleeve]
                    index = cursors[sleeve]
                    while index < len(ranking) and ranking[index] in seen:
                        index += 1
                    cursors[sleeve] = index + 1
                    if index < len(ranking):
                        symbol = ranking[index]
                        selected.append(symbol)
                        seen.add(symbol)
                        progressed = True
                        if len(selected) == capacity:
                            break
                if not progressed:
                    break

            if len(selected) != eligible_count:
                raise BoundedTerminalScreeningError(
                    f"{progress_label} complete-consideration selection did not retain "
                    "every eligible catalog record"
                )

            shadow: tuple[str, ...] = ()
            measured = tuple(selected) + shadow
            state_spool.prepare_measured(measured)
            membership_rows: list[tuple[str, tuple[str, ...]]] = []
            score_rows: list[tuple[str, tuple[tuple[str, float], ...]]] = []
            signal_observed_at: dict[str, datetime] = {}
            evidence_rows: list[tuple[str, tuple[str, ...]]] = []
            selected_ordinals: list[int] = []
            for row in state_spool.measured_rows():
                (
                    position,
                    ordinal,
                    quality,
                    value,
                    momentum,
                    carry,
                    diversification,
                    improving_conditions,
                    observed_at,
                    _indicative_price,
                    evidence_json,
                ) = row
                symbol = measured[int(position)]
                values = (
                    (CandidateSleeve.QUALITY, quality),
                    (CandidateSleeve.VALUE, value),
                    (CandidateSleeve.MOMENTUM, momentum),
                    (CandidateSleeve.CARRY, carry),
                    (CandidateSleeve.DIVERSIFICATION, diversification),
                    (
                        CandidateSleeve.IMPROVING_CONDITIONS,
                        improving_conditions,
                    ),
                )
                membership_rows.append(
                    (
                        symbol,
                        tuple(
                            sleeve.value
                            for sleeve, score in values
                            if score is not None
                        ),
                    )
                )
                score_rows.append(
                    (
                        symbol,
                        tuple(
                            (sleeve.value, round(float(score), 10))
                            for sleeve, score in values
                            if score is not None
                        ),
                    )
                )
                if observed_at is not None:
                    signal_observed_at[symbol] = datetime.fromisoformat(
                        str(observed_at)
                    )
                if evidence_json is not None:
                    evidence_rows.append(
                        (
                            symbol,
                            tuple(
                                str(identifier)
                                for identifier in json.loads(str(evidence_json))
                            ),
                        )
                    )
                selected_ordinals.append(int(ordinal))

            plan = PreselectionPlan(
                catalog_count=len(records),
                eligible_count=eligible_count,
                capacity=capacity,
                selected_symbols=tuple(selected),
                shadow_symbols=shadow,
                sleeve_rankings=tuple(
                    (sleeve.value, rankings[sleeve]) for sleeve in SLEEVES
                ),
                sleeve_membership=tuple(membership_rows),
                scores=tuple(score_rows),
                factor_coverage=state_spool.factor_coverage(),
                exclusions=state_spool.exclusions(),
            )
            nominated = tuple(records[ordinal] for ordinal in selected_ordinals)
            return BoundedTerminalPreselection(
                plan=plan,
                nominated=nominated,
                signal_prices=state_spool.signal_prices(),
                signal_observed_at=signal_observed_at,
                preselection_evidence=tuple(evidence_rows),
                provider_factor_authority_established=authority_established,
                publication_failure_reasons=tuple(sorted(publication_failures)),
                screened_signal_count=screened_signal_count,
            )


def build_bounded_cutoff_observations(
    screening: BoundedTerminalPreselection,
    *,
    asset_class: str,
    selected_prices: Mapping[str, float],
) -> tuple[CutoffObservation, ...]:
    """Rebuild the existing cutoff observations from compact retained signal fields."""

    memberships = dict(screening.plan.sleeve_membership)
    score_map = dict(screening.plan.scores)
    result: list[CutoffObservation] = []
    for cohort, symbols in (
        ("selected", screening.plan.selected_symbols),
        ("below_cutoff", screening.plan.shadow_symbols),
    ):
        for symbol in symbols:
            observed_at = screening.signal_observed_at.get(symbol)
            price = selected_prices.get(symbol) or screening.signal_prices.get(symbol)
            if observed_at is None or price is None:
                continue
            values = [value for _name, value in score_map.get(symbol, ())]
            result.append(
                CutoffObservation(
                    asset_class=asset_class,
                    symbol=symbol,
                    cohort=cohort,
                    observed_at=observed_at,
                    price=float(price),
                    sleeves=memberships.get(symbol, ()),
                    preselection_score=round(
                        fmean(values) if values else 0.0,
                        10,
                    ),
                )
            )
    return tuple(result)


__all__ = [
    "BoundedTerminalPreselection",
    "BoundedTerminalScreeningError",
    "DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE",
    "build_bounded_cutoff_observations",
    "build_bounded_terminal_preselection",
]
