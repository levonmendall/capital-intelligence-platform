"""Bound terminal all-market screening without changing admission semantics.

The canonical provider-factor publication remains complete on disk. Provider signals are
indexed by byte offset instead of copied into a second complete payload store, while
completed screening state, global sleeve rankings, complete-consideration selection,
and retained evidence are spooled through SQLite. Screening and finalization therefore
avoid overlapping all-market Python object graphs and duplicate provider payloads.
Global ranking is performed only after the complete lane is screened; no market, factor,
evidence, liquidity, freshness, ranking, threshold, or authority rule is changed.
"""
from __future__ import annotations

import gc
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
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
_DEFAULT_STORAGE_RESERVE_MIB = 64
_TOP_LEVEL_KEY = re.compile(r'^  (?P<key>"(?:\\.|[^"\\])+"): (?P<value>.*)$')
_SIGNAL_KEY = re.compile(r'^    (?P<key>"(?:\\.|[^"\\])+"): (?P<value>\{.*)$')
_SCORE_COLUMNS = {
    CandidateSleeve.QUALITY: ("quality_score", "quality_tie"),
    CandidateSleeve.VALUE: ("value_score", "value_tie"),
    CandidateSleeve.MOMENTUM: ("momentum_score", "momentum_tie"),
    CandidateSleeve.CARRY: ("carry_score", "carry_tie"),
    CandidateSleeve.DIVERSIFICATION: ("diversification_score", "diversification_tie"),
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
    preselection_evidence: Sequence[tuple[str, tuple[str, ...]]]
    provider_factor_authority_established: bool
    publication_failure_reasons: tuple[str, ...]
    screened_signal_count: int


def _advise_file_cache_dontneed(path: Path) -> None:
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
    connection.execute("PRAGMA temp_store = FILE")
    connection.execute(f"PRAGMA cache_size = -{_SQLITE_CACHE_KIB}")
    connection.execute("PRAGMA mmap_size = 0")


def _path_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _sqlite_footprint(path: Path) -> int:
    return sum(
        _path_size(candidate)
        for candidate in (
            path,
            Path(f"{path}-journal"),
            Path(f"{path}-wal"),
            Path(f"{path}-shm"),
        )
    )


def _storage_reserve_bytes() -> int:
    raw = os.environ.get(
        "MANUAL_CIO_SERVICE_STORAGE_RESERVE_MB",
        str(_DEFAULT_STORAGE_RESERVE_MIB),
    )
    try:
        reserve_mib = int(raw)
    except (TypeError, ValueError):
        reserve_mib = _DEFAULT_STORAGE_RESERVE_MIB
    return max(1, reserve_mib) * 1024 * 1024


def _storage_metrics(
    *,
    publication_path: Path,
    publication_index_path: Path,
    screening_spool_path: Path,
    chunk_path: Path | None = None,
) -> dict[str, int]:
    metrics = {
        "publication_bytes": _path_size(publication_path),
        "publication_index_bytes": _sqlite_footprint(publication_index_path),
        "screening_spool_bytes": _sqlite_footprint(screening_spool_path),
        "chunk_file_bytes": 0 if chunk_path is None else _path_size(chunk_path),
        "storage_reserve_bytes": _storage_reserve_bytes(),
    }
    try:
        usage = shutil.disk_usage(screening_spool_path.parent)
    except OSError:
        return metrics
    metrics.update(
        {
            "storage_total_bytes": int(usage.total),
            "storage_used_bytes": int(usage.used),
            "storage_free_bytes": int(usage.free),
        }
    )
    return metrics


def _ensure_storage_reserve(metrics: Mapping[str, int], *, phase: str) -> None:
    free_bytes = metrics.get("storage_free_bytes")
    reserve_bytes = metrics.get("storage_reserve_bytes")
    if free_bytes is None or reserve_bytes is None or free_bytes >= reserve_bytes:
        return
    raise BoundedTerminalScreeningError(
        f"{phase} storage reserve exhausted before filesystem capacity failure: "
        f"free_bytes={free_bytes}; reserve_bytes={reserve_bytes}"
    )


class _PublicationSignalSpool:
    """Index canonical pretty-JSON signals by byte range without duplicating payloads."""

    __slots__ = (
        "publication_path",
        "_temporary",
        "database_path",
        "connection",
        "metadata",
        "signal_count",
        "_closed",
    )

    def __init__(self, publication_path: Path) -> None:
        self.publication_path = publication_path
        self._temporary = tempfile.TemporaryDirectory(prefix="cio-terminal-screening-")
        self.database_path = Path(self._temporary.name) / "signals.sqlite3"
        self.connection = sqlite3.connect(self.database_path)
        self._closed = False
        _configure_spool_connection(self.connection)
        # This database is a disposable lookup index over the immutable canonical
        # publication. A journal would temporarily duplicate index pages on disk and is
        # unnecessary: any interruption terminates the fail-closed diagnostic and the
        # index is rebuilt from the canonical publication on the next attempt.
        self.connection.execute("PRAGMA journal_mode = OFF")
        self.connection.execute(
            "CREATE TABLE signals ("
            "symbol TEXT PRIMARY KEY, payload_offset INTEGER NOT NULL, "
            "payload_length INTEGER NOT NULL) WITHOUT ROWID"
        )
        self.metadata: dict[str, object] = {}
        self.signal_count = 0
        self._stream_publication()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
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

    def _insert_signal_reference(
        self,
        symbol: str,
        *,
        payload_offset: int,
        payload_length: int,
        value: object,
    ) -> None:
        if not isinstance(value, Mapping):
            raise BoundedTerminalScreeningError(
                "provider publication signal must be a JSON object"
            )
        if payload_offset < 0 or payload_length < 1:
            raise BoundedTerminalScreeningError(
                "provider publication signal byte range is invalid"
            )
        self.connection.execute(
            "INSERT INTO signals(symbol, payload_offset, payload_length) VALUES (?, ?, ?)",
            (symbol, payload_offset, payload_length),
        )
        self.signal_count += 1

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
        signal_payload_offset: int | None = None
        saw_signals = False
        try:
            handle = self.publication_path.open("rb")
        except OSError as error:
            raise BoundedTerminalScreeningError(
                "provider preselection publication cannot be opened"
            ) from error
        with handle:
            while True:
                line_start = handle.tell()
                raw_line = handle.readline()
                if not raw_line:
                    break
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise BoundedTerminalScreeningError(
                        "provider preselection publication is not UTF-8"
                    ) from error

                if mode == "signals":
                    if signal_symbol is not None:
                        signal_value += line
                        decoded = self._decode_value(signal_value)
                        if decoded is not None:
                            value, end = decoded
                            if signal_payload_offset is None:
                                raise BoundedTerminalScreeningError(
                                    "provider publication signal byte range is unavailable"
                                )
                            payload_length = len(
                                signal_value[:end].encode("utf-8")
                            )
                            self._insert_signal_reference(
                                signal_symbol,
                                payload_offset=signal_payload_offset,
                                payload_length=payload_length,
                                value=value,
                            )
                            signal_symbol = None
                            signal_value = ""
                            signal_payload_offset = None
                        continue
                    if line.startswith("  }"):
                        mode = "top"
                        continue
                    match = _SIGNAL_KEY.match(line.rstrip("\r\n"))
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
                    value_start = match.start("value")
                    signal_payload_offset = line_start + len(
                        line[:value_start].encode("utf-8")
                    )
                    signal_value = line[value_start:]
                    decoded = self._decode_value(signal_value)
                    if decoded is not None:
                        value, end = decoded
                        payload_length = len(signal_value[:end].encode("utf-8"))
                        self._insert_signal_reference(
                            signal_symbol,
                            payload_offset=signal_payload_offset,
                            payload_length=payload_length,
                            value=value,
                        )
                        signal_symbol = None
                        signal_value = ""
                        signal_payload_offset = None
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

                match = _TOP_LEVEL_KEY.match(line.rstrip("\r\n"))
                if match is None:
                    continue
                key = str(json.loads(match.group("key")))
                value_text = line[match.start("value"):]
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
            raise BoundedTerminalScreeningError("unsupported provider preselection schema")
        if "available_at" not in self.metadata:
            raise BoundedTerminalScreeningError(
                "provider preselection publication available_at is missing"
            )
        self.connection.commit()
        _advise_file_cache_dontneed(self.publication_path)
        self.release_cached_pages()

    def release_cached_pages(self) -> None:
        if not self._closed:
            _advise_file_cache_dontneed(self.database_path)

    def signals_for(self, records: Sequence[object]) -> dict[str, object]:
        result: dict[str, object] = {}
        cursor = self.connection.cursor()
        try:
            handle = self.publication_path.open("rb")
        except OSError as error:
            raise BoundedTerminalScreeningError(
                "provider preselection publication cannot be reopened"
            ) from error
        with handle:
            for record in records:
                symbol = str(getattr(record, "symbol", "")).strip().upper()
                provider_symbol = str(
                    getattr(record, "provider_symbol", symbol)
                ).strip().upper()
                row = cursor.execute(
                    "SELECT payload_offset, payload_length FROM signals WHERE symbol = ?",
                    (symbol,),
                ).fetchone()
                if row is None and provider_symbol and provider_symbol != symbol:
                    row = cursor.execute(
                        "SELECT payload_offset, payload_length FROM signals WHERE symbol = ?",
                        (provider_symbol,),
                    ).fetchone()
                if row is None:
                    continue
                payload_offset, payload_length = int(row[0]), int(row[1])
                handle.seek(payload_offset)
                payload = handle.read(payload_length)
                if len(payload) != payload_length:
                    raise BoundedTerminalScreeningError(
                        "provider publication signal byte range is incomplete"
                    )
                try:
                    value = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise BoundedTerminalScreeningError(
                        "provider publication indexed signal is invalid"
                    ) from error
                if not isinstance(value, Mapping):
                    raise BoundedTerminalScreeningError(
                        "provider publication indexed signal must be a JSON object"
                    )
                result[symbol] = value
        return result

    def chunk_publication(self, records: Sequence[object], target: Path) -> None:
        target.write_text(
            json.dumps(
                {
                    "schema_version": self.metadata["schema_version"],
                    "available_at": self.metadata["available_at"],
                    "source_identifiers": self.metadata.get("source_identifiers", ()),
                    "signals": self.signals_for(records),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )


class _TerminalScreeningStateSpool:
    """Persist screened state, global rankings, selection, and evidence on disk."""

    __slots__ = (
        "_temporary",
        "database_path",
        "connection",
        "_detached",
        "_closed",
    )

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="cio-terminal-state-")
        self.database_path = Path(self._temporary.name) / "screening.sqlite3"
        self.connection = sqlite3.connect(self.database_path)
        self._detached = False
        self._closed = False
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
            CREATE UNIQUE INDEX screened_symbol_idx ON screened(symbol);
            CREATE TABLE exclusions (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.connection.close()
        finally:
            self._temporary.cleanup()

    def detach(self) -> "_TerminalScreeningStateSpool":
        """Transfer lifecycle ownership to a returned disk-backed view."""
        self._detached = True
        return self

    def __enter__(self) -> "_TerminalScreeningStateSpool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._detached:
            self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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
                None if signal.indicative_price is None else float(signal.indicative_price)
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
                    CandidateSleeve.IMPROVING_CONDITIONS: signal.improving_conditions_score,
                }
        ties = {sleeve: _tie(as_of, sleeve, symbol) for sleeve in SLEEVES}
        self.connection.execute(
            """
            INSERT INTO screened(
                ordinal, symbol, eligible,
                bucket_exposure, bucket_venue, bucket_country, bucket_currency,
                observed_at, indicative_price, evidence_json,
                quality_score, quality_tie, value_score, value_tie,
                momentum_score, momentum_tie, carry_score, carry_tie,
                diversification_score, diversification_tie,
                improving_conditions_score, improving_conditions_tie
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?
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
        if not self._closed:
            _advise_file_cache_dontneed(self.database_path)

    def commit_chunk(self) -> None:
        self.connection.commit()
        self.release_cached_pages()

    def finalize_diversification(
        self,
        *,
        batch_size: int = 512,
        progress_label: str | None = None,
    ) -> None:
        """Finalize exact global diversification scores in bounded disk-backed passes."""
        self.connection.execute("DROP TABLE IF EXISTS diversification_bucket_counts")
        self.connection.execute(
            "CREATE TABLE diversification_bucket_counts("
            "bucket_exposure TEXT NOT NULL, bucket_venue TEXT NOT NULL, "
            "bucket_country TEXT NOT NULL, bucket_currency TEXT NOT NULL, "
            "member_count INTEGER NOT NULL, "
            "PRIMARY KEY(bucket_exposure, bucket_venue, bucket_country, bucket_currency)"
            ") WITHOUT ROWID"
        )
        self.connection.commit()
        self.release_cached_pages()

        total_records = self.eligible_count
        progress_stride = max(1024, batch_size)

        def record_progress(phase: str, processed_records: int) -> None:
            if progress_label is None:
                return
            metrics = {
                "processed_records": processed_records,
                "total_records": total_records,
                "chunk_records": 0,
                "screening_spool_bytes": _sqlite_footprint(self.database_path),
                "storage_reserve_bytes": _storage_reserve_bytes(),
            }
            try:
                usage = shutil.disk_usage(self.database_path.parent)
            except OSError:
                pass
            else:
                metrics.update(
                    {
                        "storage_total_bytes": int(usage.total),
                        "storage_used_bytes": int(usage.used),
                        "storage_free_bytes": int(usage.free),
                    }
                )
            stage = f"terminal_screening_finalize_{phase}:{progress_label}"
            record_manual_cio_diagnostic_progress(stage, metrics=metrics)
            _ensure_storage_reserve(metrics, phase=stage)

        if total_records == 0:
            record_progress("diversification_count", 0)
            record_progress("diversification_apply", 0)
            self.connection.execute("DROP TABLE diversification_bucket_counts")
            self.connection.commit()
            self.release_cached_pages()
            return

        # Build exact global bucket counts incrementally. Keyset pagination follows
        # the screened INTEGER PRIMARY KEY, so SQLite never needs a global GROUP BY,
        # derived-table join, or sort to materialize the complete eligible lane.
        processed = 0
        last_ordinal = -1
        next_progress_at = 0
        while processed < total_records:
            rows = self.connection.execute(
                "SELECT ordinal, bucket_exposure, bucket_venue, bucket_country, "
                "bucket_currency FROM screened "
                "WHERE eligible = 1 AND ordinal > ? ORDER BY ordinal LIMIT ?",
                (last_ordinal, batch_size),
            ).fetchall()
            if not rows:
                break
            batch_records = len(rows)
            last_ordinal = int(rows[-1][0])
            self.connection.executemany(
                "INSERT INTO diversification_bucket_counts("
                "bucket_exposure, bucket_venue, bucket_country, bucket_currency, "
                "member_count) VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(bucket_exposure, bucket_venue, bucket_country, "
                "bucket_currency) DO UPDATE SET member_count = member_count + 1",
                (tuple(row[1:5]) for row in rows),
            )
            self.connection.commit()
            processed += batch_records
            del rows
            self.release_cached_pages()
            if processed >= next_progress_at or processed == total_records:
                record_progress("diversification_count", processed)
                next_progress_at = processed + progress_stride

        if processed != total_records:
            raise BoundedTerminalScreeningError(
                "diversification count pass did not inspect every eligible catalog record"
            )

        # Apply the exact 1/member_count score with only one bounded row batch and
        # one bounded per-batch bucket lookup cache resident in Python at a time.
        processed = 0
        last_ordinal = -1
        next_progress_at = 0
        while processed < total_records:
            rows = self.connection.execute(
                "SELECT ordinal, bucket_exposure, bucket_venue, bucket_country, "
                "bucket_currency FROM screened "
                "WHERE eligible = 1 AND ordinal > ? ORDER BY ordinal LIMIT ?",
                (last_ordinal, batch_size),
            ).fetchall()
            if not rows:
                break
            batch_records = len(rows)
            last_ordinal = int(rows[-1][0])
            bucket_cache: dict[tuple[str, str, str, str], int] = {}
            updates: list[tuple[float, int]] = []
            for row in rows:
                bucket = tuple(str(value) for value in row[1:5])
                member_count = bucket_cache.get(bucket)
                if member_count is None:
                    count_row = self.connection.execute(
                        "SELECT member_count FROM diversification_bucket_counts "
                        "WHERE bucket_exposure = ? AND bucket_venue = ? "
                        "AND bucket_country = ? AND bucket_currency = ?",
                        bucket,
                    ).fetchone()
                    if count_row is None or int(count_row[0]) < 1:
                        raise BoundedTerminalScreeningError(
                            "diversification bucket count is unavailable for an "
                            "eligible catalog record"
                        )
                    member_count = int(count_row[0])
                    bucket_cache[bucket] = member_count
                updates.append((1.0 / member_count, int(row[0])))
            self.connection.executemany(
                "UPDATE screened SET diversification_score = ? WHERE ordinal = ?",
                updates,
            )
            self.connection.commit()
            processed += batch_records
            del updates
            del bucket_cache
            del rows
            self.release_cached_pages()
            if processed >= next_progress_at or processed == total_records:
                record_progress("diversification_apply", processed)
                next_progress_at = processed + progress_stride

        if processed != total_records:
            raise BoundedTerminalScreeningError(
                "diversification score pass did not update every eligible catalog record"
            )

        self.connection.execute("DROP TABLE diversification_bucket_counts")
        self.connection.commit()
        self.release_cached_pages()

    @property
    def eligible_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM screened WHERE eligible = 1"
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def build_rankings(self, *, batch_size: int = 512) -> None:
        """Persist all global sleeve rankings one sleeve at a time."""
        self.connection.execute("DROP TABLE IF EXISTS rankings")
        self.connection.execute(
            "CREATE TABLE rankings("
            "sleeve TEXT NOT NULL, position INTEGER NOT NULL, symbol TEXT NOT NULL, "
            "PRIMARY KEY(sleeve, position)) WITHOUT ROWID"
        )
        for sleeve in SLEEVES:
            score_column, tie_column = _SCORE_COLUMNS[sleeve]
            cursor = self.connection.execute(
                "SELECT symbol FROM screened "
                f"WHERE eligible = 1 AND {score_column} IS NOT NULL "
                f"ORDER BY {score_column} DESC, {tie_column} DESC, symbol DESC"
            )
            position = 0
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                self.connection.executemany(
                    "INSERT INTO rankings(sleeve, position, symbol) VALUES (?, ?, ?)",
                    (
                        (sleeve.value, position + offset, str(row[0]))
                        for offset, row in enumerate(rows)
                    ),
                )
                position += len(rows)
            self.connection.commit()
            self.release_cached_pages()

    def ranking(self, sleeve: CandidateSleeve) -> tuple[str, ...]:
        return tuple(
            str(row[0])
            for row in self.connection.execute(
                "SELECT symbol FROM rankings WHERE sleeve = ? ORDER BY position",
                (sleeve.value,),
            )
        )

    def select_complete_consideration(self, *, capacity: int) -> int:
        """Reproduce sleeve round-robin selection while retaining state on disk."""
        self.connection.execute("DROP TABLE IF EXISTS selection")
        self.connection.execute(
            "CREATE TABLE selection("
            "position INTEGER PRIMARY KEY, symbol TEXT NOT NULL UNIQUE)"
        )
        target = min(capacity, self.eligible_count)
        ranking_cursors = {
            sleeve: self.connection.execute(
                "SELECT symbol FROM rankings WHERE sleeve = ? ORDER BY position",
                (sleeve.value,),
            )
            for sleeve in SLEEVES
        }
        selected_count = 0
        while selected_count < target:
            progressed = False
            for sleeve in SLEEVES:
                cursor = ranking_cursors[sleeve]
                while True:
                    row = cursor.fetchone()
                    if row is None:
                        break
                    symbol = str(row[0])
                    inserted = self.connection.execute(
                        "INSERT OR IGNORE INTO selection(position, symbol) VALUES (?, ?)",
                        (selected_count, symbol),
                    )
                    if inserted.rowcount == 1:
                        selected_count += 1
                        progressed = True
                        break
                if selected_count == target:
                    break
            if not progressed:
                break
        self.connection.commit()
        self.release_cached_pages()
        return selected_count

    def selected_symbols(self) -> tuple[str, ...]:
        return tuple(
            str(row[0])
            for row in self.connection.execute(
                "SELECT symbol FROM selection ORDER BY position"
            )
        )

    def selected_ordinals(self):
        return self.connection.execute(
            """
            SELECT screened.ordinal
            FROM selection
            JOIN screened ON screened.symbol = selection.symbol
            ORDER BY selection.position
            """
        )

    def measured_rows(self):
        return self.connection.execute(
            """
            SELECT selection.position,
                   screened.quality_score, screened.value_score,
                   screened.momentum_score, screened.carry_score,
                   screened.diversification_score,
                   screened.improving_conditions_score,
                   screened.observed_at
            FROM selection
            JOIN screened ON screened.symbol = selection.symbol
            ORDER BY selection.position
            """
        )

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

    def signal_prices(self) -> dict[str, float]:
        return {
            str(symbol): float(price)
            for symbol, price in self.connection.execute(
                "SELECT symbol, indicative_price FROM screened "
                "WHERE indicative_price IS NOT NULL ORDER BY ordinal"
            )
        }

    def evidence_count(self) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM selection
            JOIN screened ON screened.symbol = selection.symbol
            WHERE screened.evidence_json IS NOT NULL
            """
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def evidence_rows(self) -> Iterator[tuple[str, tuple[str, ...]]]:
        cursor = self.connection.execute(
            """
            SELECT screened.symbol, screened.evidence_json
            FROM selection
            JOIN screened ON screened.symbol = selection.symbol
            WHERE screened.evidence_json IS NOT NULL
            ORDER BY selection.position
            """
        )
        for symbol, evidence_json in cursor:
            identifiers = json.loads(str(evidence_json))
            yield (
                str(symbol),
                tuple(str(identifier) for identifier in identifiers),
            )


class _DiskBackedEvidenceSequence(Sequence[tuple[str, tuple[str, ...]]]):
    """Expose complete retained lineage without copying it into the Python heap."""

    __slots__ = ("_spool",)

    def __init__(self, spool: _TerminalScreeningStateSpool) -> None:
        self._spool = spool

    def __len__(self) -> int:
        return self._spool.evidence_count()

    def __iter__(self) -> Iterator[tuple[str, tuple[str, ...]]]:
        return self._spool.evidence_rows()

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self)[index]
        position = int(index)
        if position < 0:
            position += len(self)
        if position < 0:
            raise IndexError(index)
        row = self._spool.connection.execute(
            """
            SELECT screened.symbol, screened.evidence_json
            FROM selection
            JOIN screened ON screened.symbol = selection.symbol
            WHERE screened.evidence_json IS NOT NULL
            ORDER BY selection.position
            LIMIT 1 OFFSET ?
            """,
            (position,),
        ).fetchone()
        if row is None:
            raise IndexError(index)
        identifiers = json.loads(str(row[1]))
        return str(row[0]), tuple(str(identifier) for identifier in identifiers)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Sequence):
            return False
        return tuple(self) == tuple(other)


def _chunks(values: Sequence[object], size: int):
    for start in range(0, len(values), size):
        yield start, values[start : start + size]


def _finalization_progress(
    phase: str,
    progress_label: str,
    *,
    processed_records: int,
    total_records: int,
) -> None:
    record_manual_cio_diagnostic_progress(
        f"terminal_screening_finalize_{phase}:{progress_label}",
        metrics={
            "processed_records": processed_records,
            "total_records": total_records,
            "chunk_records": 0,
        },
    )


def build_bounded_terminal_preselection(
    records: Sequence[object],
    *,
    as_of: datetime,
    policy: object,
    progress_label: str,
    chunk_size: int = DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE,
) -> BoundedTerminalPreselection:
    """Reproduce complete-consideration preselection with bounded disk-backed state."""
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
                initial_storage = _storage_metrics(
                    publication_path=publication_path,
                    publication_index_path=publication_spool.database_path,
                    screening_spool_path=state_spool.database_path,
                    chunk_path=chunk_path,
                )
                _ensure_storage_reserve(
                    initial_storage,
                    phase=f"terminal_screening:{progress_label}",
                )
                for start, chunk in _chunks(records, chunk_size):
                    before_chunk = _storage_metrics(
                        publication_path=publication_path,
                        publication_index_path=publication_spool.database_path,
                        screening_spool_path=state_spool.database_path,
                        chunk_path=chunk_path,
                    )
                    _ensure_storage_reserve(
                        before_chunk,
                        phase=f"terminal_screening_chunk:{progress_label}",
                    )
                    publication_spool.chunk_publication(chunk, chunk_path)
                    chunk_policy = replace(
                        policy, provider_preselection_path=str(chunk_path)
                    )
                    signals = provider_enriched_catalog_screening_signals(
                        chunk, timestamp, chunk_policy
                    )
                    if not isinstance(signals, Mapping):
                        raise BoundedTerminalScreeningError(
                            "provider-enriched screening chunk did not return a mapping"
                        )
                    signals = validate_provider_enriched_signals(
                        chunk,
                        signals,
                        required_factors=getattr(
                            policy, "required_provider_preselection_factors"
                        ),
                    )
                    normalized_signals = {
                        str(symbol).strip().upper(): signal
                        for symbol, signal in signals.items()
                    }
                    # The provider reader has completed; no later stage needs the
                    # materialized chunk publication. Unlink it before growing retained
                    # screening state so those disk footprints do not overlap.
                    try:
                        chunk_path.unlink(missing_ok=True)
                    except OSError:
                        _advise_file_cache_dontneed(chunk_path)
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
                    publication_spool.release_cached_pages()
                    state_spool.release_cached_pages()
                    progress_metrics = {
                        "processed_records": processed,
                        "total_records": len(records),
                        "chunk_records": len(chunk),
                        **_storage_metrics(
                            publication_path=publication_path,
                            publication_index_path=publication_spool.database_path,
                            screening_spool_path=state_spool.database_path,
                            chunk_path=chunk_path,
                        ),
                    }
                    record_manual_cio_diagnostic_progress(
                        f"terminal_screening_chunk:{progress_label}",
                        metrics=progress_metrics,
                    )
                    _ensure_storage_reserve(
                        progress_metrics,
                        phase=f"terminal_screening_chunk:{progress_label}",
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

            record_manual_cio_diagnostic_progress(
                f"terminal_screening:{progress_label}",
                metrics={
                    "processed_records": len(records),
                    "total_records": len(records),
                    "chunk_records": 0,
                    **_storage_metrics(
                        publication_path=publication_path,
                        publication_index_path=publication_spool.database_path,
                        screening_spool_path=state_spool.database_path,
                    ),
                },
            )

            # The publication offset index is no longer needed after every record has
            # been durably screened. Releasing it before ranking prevents even the compact
            # lookup index and finalization state from overlapping unnecessarily.
            publication_spool.release_cached_pages()
            publication_spool.close()
            gc.collect()
            _finalization_progress(
                "release",
                progress_label,
                processed_records=len(records),
                total_records=len(records),
            )

            batch_size = min(chunk_size, DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE)
            state_spool.finalize_diversification(
                batch_size=batch_size,
                progress_label=progress_label,
            )
            _finalization_progress(
                "diversification",
                progress_label,
                processed_records=len(records),
                total_records=len(records),
            )

            state_spool.build_rankings(batch_size=batch_size)
            _finalization_progress(
                "rankings",
                progress_label,
                processed_records=len(records),
                total_records=len(records),
            )

            eligible_count = state_spool.eligible_count
            capacity = max(1, len(records))
            selected_count = state_spool.select_complete_consideration(capacity=capacity)
            if selected_count != eligible_count:
                raise BoundedTerminalScreeningError(
                    f"{progress_label} complete-consideration selection did not retain "
                    "every eligible catalog record"
                )
            _finalization_progress(
                "selection",
                progress_label,
                processed_records=selected_count,
                total_records=eligible_count,
            )

            selected_symbols = state_spool.selected_symbols()
            shadow: tuple[str, ...] = ()
            membership_rows: list[tuple[str, tuple[str, ...]]] = []
            score_rows: list[tuple[str, tuple[tuple[str, float], ...]]] = []
            signal_observed_at: dict[str, datetime] = {}
            for row in state_spool.measured_rows():
                (
                    position,
                    quality,
                    value,
                    momentum,
                    carry,
                    diversification,
                    improving_conditions,
                    observed_at,
                ) = row
                symbol = selected_symbols[int(position)]
                values = (
                    (CandidateSleeve.QUALITY, quality),
                    (CandidateSleeve.VALUE, value),
                    (CandidateSleeve.MOMENTUM, momentum),
                    (CandidateSleeve.CARRY, carry),
                    (CandidateSleeve.DIVERSIFICATION, diversification),
                    (CandidateSleeve.IMPROVING_CONDITIONS, improving_conditions),
                )
                membership_rows.append(
                    (
                        symbol,
                        tuple(
                            sleeve.value for sleeve, score in values if score is not None
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
                    signal_observed_at[symbol] = datetime.fromisoformat(str(observed_at))

            sleeve_rankings = tuple(
                (sleeve.value, state_spool.ranking(sleeve)) for sleeve in SLEEVES
            )
            factor_coverage = state_spool.factor_coverage()
            exclusions = state_spool.exclusions()
            signal_prices = state_spool.signal_prices()
            nominated = tuple(
                records[int(row[0])] for row in state_spool.selected_ordinals()
            )
            plan = PreselectionPlan(
                catalog_count=len(records),
                eligible_count=eligible_count,
                capacity=capacity,
                selected_symbols=selected_symbols,
                shadow_symbols=shadow,
                sleeve_rankings=sleeve_rankings,
                sleeve_membership=tuple(membership_rows),
                scores=tuple(score_rows),
                factor_coverage=factor_coverage,
                exclusions=exclusions,
            )
            _finalization_progress(
                "plan",
                progress_label,
                processed_records=eligible_count,
                total_records=eligible_count,
            )

            # Evidence can dominate retained finalization memory because each asset may
            # carry several long lineage identifiers. Keep it in the already durable
            # screening spool and expose a complete lazy sequence. The sequence owns the
            # spool lifecycle and preserves every identifier and selection order.
            preselection_evidence = _DiskBackedEvidenceSequence(state_spool.detach())
            return BoundedTerminalPreselection(
                plan=plan,
                nominated=nominated,
                signal_prices=signal_prices,
                signal_observed_at=signal_observed_at,
                preselection_evidence=preselection_evidence,
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
                    preselection_score=round(fmean(values) if values else 0.0, 10),
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
