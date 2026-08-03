"""Disk-backed streaming evidence collection for broad paper-candidate analysis.

Provider payloads are persisted per symbol before the next bounded batch is requested.
The resulting mappings load one symbol at a time, preventing complete multi-year market
histories and SEC fact sets from accumulating in process memory. The spool has no
candidate, CIO, construction, execution, or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from data import CompanyFact

_POLICY_VERSION = "paper-evidence-symbol-spool.v1"
_DEFAULT_LISTED_BATCH_SIZE = 10
_STALE_SPOOL_AGE = timedelta(days=2)
_TYPE_FIELD = "__capital_intelligence_type__"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return {_TYPE_FIELD: "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_FIELD: "date", "value": value.isoformat()}
    if isinstance(value, CompanyFact):
        return {_TYPE_FIELD: "CompanyFact", "value": asdict(value)}
    raise TypeError(f"unsupported evidence value: {type(value).__name__}")


def _json_hook(value: dict[str, object]) -> object:
    value_type = value.get(_TYPE_FIELD)
    raw = value.get("value")
    if value_type == "datetime" and isinstance(raw, str):
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return _aware(parsed, field_name="persisted datetime")
    if value_type == "date" and isinstance(raw, str):
        return date.fromisoformat(raw)
    if value_type == "CompanyFact" and isinstance(raw, dict):
        return CompanyFact(**raw)
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _spool_directory() -> Path:
    explicit = os.getenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    data_dir = Path(
        os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return data_dir / "paper_evidence_spool"


def _cleanup_stale_spools(directory: Path, *, now: datetime) -> None:
    cutoff = now.timestamp() - _STALE_SPOOL_AGE.total_seconds()
    for path in directory.glob("paper-evidence-*.db*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue


class SQLiteEvidenceMapping(Mapping[str, object]):
    """Read-only lazy namespace view over one evidence spool."""

    def __init__(
        self,
        spool: "SQLitePaperEvidenceSpool",
        namespace: str,
        *,
        tuple_result: bool = False,
    ) -> None:
        self._spool = spool
        self._namespace = str(namespace).strip()
        self._tuple_result = bool(tuple_result)
        if not self._namespace:
            raise ValueError("namespace cannot be empty")

    def __getitem__(self, key: str) -> object:
        value = self._spool.read(self._namespace, str(key).strip().upper())
        if self._tuple_result and isinstance(value, list):
            return tuple(value)
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(self._spool.keys(self._namespace))

    def __len__(self) -> int:
        return self._spool.count(self._namespace)


class SQLitePaperEvidenceSpool:
    """Append-only cycle-local provider evidence persisted outside process memory."""

    policy_version = _POLICY_VERSION

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._removed = False
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_entries (
                    namespace TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, symbol)
                );
                CREATE TRIGGER IF NOT EXISTS evidence_entries_no_update
                BEFORE UPDATE ON evidence_entries
                BEGIN SELECT RAISE(ABORT, 'paper evidence spool is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS evidence_entries_no_delete
                BEFORE DELETE ON evidence_entries
                BEGIN SELECT RAISE(ABORT, 'paper evidence spool is append-only'); END;
                """
            )

    @classmethod
    def create(
        cls,
        *,
        universe_identifier: str,
        as_of: datetime,
    ) -> "SQLitePaperEvidenceSpool":
        timestamp = _aware(as_of, field_name="as_of")
        directory = _spool_directory()
        directory.mkdir(parents=True, exist_ok=True)
        _cleanup_stale_spools(directory, now=timestamp)
        digest = hashlib.sha256(
            f"{universe_identifier}|{timestamp.isoformat()}".encode("utf-8")
        ).hexdigest()[:12]
        path = directory / (
            f"paper-evidence-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{digest}-{uuid4().hex[:8]}.db"
        )
        return cls(path)

    def append(
        self,
        namespace: str,
        symbol: str,
        value: object,
        *,
        recorded_at: datetime,
    ) -> None:
        if self._removed:
            raise RuntimeError("paper evidence spool is closed")
        normalized_namespace = str(namespace).strip()
        normalized_symbol = str(symbol).strip().upper()
        if not normalized_namespace or not normalized_symbol:
            raise ValueError("namespace and symbol cannot be empty")
        payload = _canonical_json(value)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        timestamp = _aware(recorded_at, field_name="recorded_at")
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                "SELECT payload_hash FROM evidence_entries "
                "WHERE namespace = ? AND symbol = ?",
                (normalized_namespace, normalized_symbol),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise ValueError(
                        "paper evidence entry already exists with different content"
                    )
                return
            connection.execute(
                "INSERT INTO evidence_entries VALUES (?, ?, ?, ?, ?)",
                (
                    normalized_namespace,
                    normalized_symbol,
                    payload,
                    digest,
                    timestamp.isoformat(),
                ),
            )

    def read(self, namespace: str, symbol: str) -> object:
        if self._removed:
            raise KeyError(symbol)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM evidence_entries "
                "WHERE namespace = ? AND symbol = ?",
                (namespace, symbol),
            ).fetchone()
        if row is None:
            raise KeyError(symbol)
        return json.loads(row[0], object_hook=_json_hook)

    def keys(self, namespace: str) -> tuple[str, ...]:
        if self._removed:
            return ()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT symbol FROM evidence_entries "
                "WHERE namespace = ? ORDER BY symbol",
                (namespace,),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def count(self, namespace: str) -> int:
        if self._removed:
            return 0
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM evidence_entries WHERE namespace = ?",
                (namespace,),
            ).fetchone()
        return int(0 if row is None else row[0])

    def mapping(
        self,
        namespace: str,
        *,
        tuple_result: bool = False,
    ) -> SQLiteEvidenceMapping:
        return SQLiteEvidenceMapping(
            self,
            namespace,
            tuple_result=tuple_result,
        )

    def close(self, *, remove: bool = True) -> None:
        if self._removed:
            return
        if remove:
            for suffix in ("", "-wal", "-shm", "-journal"):
                try:
                    Path(str(self.path) + suffix).unlink(missing_ok=True)
                except OSError:
                    continue
            self._removed = True

    def __del__(self) -> None:
        try:
            self.close(remove=True)
        except Exception:
            pass


def _batches(values: Sequence[object], size: int) -> Iterator[tuple[object, ...]]:
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("batch size must be a positive integer")
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


def collect_spooled_paper_evidence(
    universe,
    decision_as_of: datetime,
    *,
    create_alpaca_client: Callable[[], object],
    sec_provider_factory: Callable[[], object],
    fred_provider_factory: Callable[[], object],
    direct_market_client_type: type,
    direct_market_universe_type: type,
    filing_query_type: type,
    candidate_asset_class: type,
    instrument_evaluation_scheduled: Callable[[object, datetime], bool],
    history_days: int,
    listed_batch_size: int = _DEFAULT_LISTED_BATCH_SIZE,
) -> Mapping[str, object]:
    """Collect full evidence scope through bounded provider batches and lazy storage."""

    as_of = _aware(decision_as_of, field_name="decision_as_of")
    scheduled_instruments = tuple(
        item
        for item in universe.instruments
        if instrument_evaluation_scheduled(item, as_of)
    )
    scheduled_closed_symbols = tuple(
        item.symbol for item in universe.instruments if item not in scheduled_instruments
    )
    listed_instruments = tuple(
        item for item in scheduled_instruments if not item.uses_direct_market_provider
    )
    direct_instruments = tuple(
        item for item in scheduled_instruments if item.uses_direct_market_provider
    )
    spool = SQLitePaperEvidenceSpool.create(
        universe_identifier=universe.identifier,
        as_of=as_of,
    )
    client = None
    direct_market_errors: dict[str, str] = {}
    try:
        if listed_instruments:
            client = create_alpaca_client()
            for raw_batch in _batches(listed_instruments, listed_batch_size):
                batch = tuple(raw_batch)
                symbols = tuple(item.symbol for item in batch)
                batch_bars = client.historical_bars(
                    symbols,
                    start=as_of - timedelta(days=history_days),
                    end=as_of,
                    timeframe="1Day",
                )
                batch_quotes = client.latest_quotes(symbols)
                for symbol in symbols:
                    if symbol in batch_bars:
                        spool.append(
                            "bars",
                            symbol,
                            batch_bars[symbol],
                            recorded_at=as_of,
                        )
                    if symbol in batch_quotes:
                        spool.append(
                            "quotes",
                            symbol,
                            batch_quotes[symbol],
                            recorded_at=as_of,
                        )
                del batch_bars
                del batch_quotes

        if direct_instruments:
            direct_client = direct_market_client_type(
                direct_market_universe_type(
                    identifier=f"dynamic-direct-evidence:{universe.identifier}",
                    provider_identifier="comprehensive-direct-market-evidence.v1",
                    instruments=direct_instruments,
                    limitations=universe.limitations,
                )
            )
            for instrument in direct_instruments:
                symbol = instrument.symbol
                try:
                    symbol_bars = direct_client.historical_bars(
                        (symbol,),
                        start=as_of - timedelta(days=history_days),
                        end=as_of,
                        timeframe="1Day",
                    )
                    symbol_quotes = direct_client.latest_quotes((symbol,))
                except (OSError, TypeError, ValueError, RuntimeError) as error:
                    direct_market_errors[symbol] = (
                        f"{type(error).__name__}: {str(error)[:300]}"
                    )
                    continue
                if symbol in symbol_bars:
                    spool.append(
                        "bars",
                        symbol,
                        symbol_bars[symbol],
                        recorded_at=as_of,
                    )
                if symbol in symbol_quotes:
                    spool.append(
                        "quotes",
                        symbol,
                        symbol_quotes[symbol],
                        recorded_at=as_of,
                    )
                del symbol_bars
                del symbol_quotes

        fred = fred_provider_factory()
        macro = {
            series: fred.get_latest_value(series)
            for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF")
        }
        stock_instruments = tuple(
            item
            for item in scheduled_instruments
            if item.execution_asset_class is candidate_asset_class.US_EQUITY
            and item.instrument_type == "common_stock"
        )
        if stock_instruments:
            sec = sec_provider_factory()
            for instrument in stock_instruments:
                if instrument.issuer_cik is None:
                    continue
                facts = sec.fetch_company_facts(
                    filing_query_type(
                        cik=instrument.issuer_cik,
                        as_of=as_of,
                        forms=(
                            "10-K",
                            "10-K/A",
                            "20-F",
                            "20-F/A",
                            "40-F",
                            "40-F/A",
                        ),
                        limit=10_000,
                    )
                )
                spool.append(
                    "company_facts",
                    instrument.symbol,
                    facts,
                    recorded_at=as_of,
                )
                del facts

        provider_clock = (
            client.clock()
            if client is not None
            else {
                "timestamp": as_of.isoformat(),
                "is_open": False,
                "source": "governed_collection_clock",
            }
        )
    except Exception:
        spool.close(remove=True)
        raise

    return {
        "bars": spool.mapping("bars"),
        "quotes": spool.mapping("quotes"),
        "macro": macro,
        "company_facts": spool.mapping("company_facts", tuple_result=True),
        "provider_clock": provider_clock,
        "_direct_market_errors": direct_market_errors,
        "_scheduled_closed_symbols": scheduled_closed_symbols,
        "_evidence_spool": spool,
        "_evidence_spool_policy": spool.policy_version,
    }


def close_spooled_paper_evidence(payload: Mapping[str, object]) -> None:
    spool = payload.get("_evidence_spool")
    if isinstance(spool, SQLitePaperEvidenceSpool):
        spool.close(remove=True)


__all__ = [
    "SQLiteEvidenceMapping",
    "SQLitePaperEvidenceSpool",
    "close_spooled_paper_evidence",
    "collect_spooled_paper_evidence",
]
