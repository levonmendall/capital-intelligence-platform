"""Resume bounded provider exchange work across exact-epoch fanout attempts.

This bootstrap is intentionally inert outside the provider-acquisition child process launched
by ``operations.epoch_scoped_provider_acquisition``.  That child already spills normalized
provider signals to SQLite to remain inside the production memory boundary, but the canonical
implementation owns that SQLite file through ``TemporaryDirectory``.  If the unchanged
300-second acceleration deadline terminates a large lane, completed exchange snapshots are
therefore discarded and the next exact-epoch attempt starts the lane from zero.

The repair below changes only that child-local storage lifetime.  It preserves the canonical
provider collector, catalog fingerprint, scoring, publication verification, 900-second evidence
freshness boundary, 300-second acceleration ceiling, 480-second downstream reserve, 180-second
stall boundary, and all investment/governance authority.  A checkpoint is usable only for the
same exact catalog fingerprint and for at most 900 seconds from the first acquisition epoch.
Each exchange is marked complete only after the canonical exchange collector returns success
and the SQLite transaction is durably committed.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

_TARGET_MODULE = "operations.epoch_scoped_provider_acquisition"
_CHECKPOINT_SCHEMA = "provider-preselection-exchange-checkpoint.v1"
_MAX_CHECKPOINT_AGE_SECONDS = 900.0
_SQLITE_CACHE_KIB = 2048


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_epoch_provider_child(argv: tuple[str, ...] | None = None) -> bool:
    values = tuple(argv if argv is not None else getattr(sys, "orig_argv", sys.argv))
    try:
        module_index = values.index("-m") + 1
    except ValueError:
        return False
    if module_index >= len(values) or values[module_index] != _TARGET_MODULE:
        return False
    return "--prepare-structure" not in values


def _checkpoint_path(publication_path: Path) -> Path:
    return publication_path.with_name(publication_path.name + ".exchange-checkpoint.sqlite3")


def _unlink_sqlite(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            # A path derived from the governed publication must never be replaced or followed
            # merely to salvage advisory acceleration state.  The subsequent open will fail
            # closed if the file is unusable.
            pass


class _DurableSignalStore:
    """Canonical signal-store interface backed by a short-lived durable checkpoint."""

    def __init__(
        self,
        path: Path,
        *,
        catalog_fingerprint: str,
        as_of: datetime,
        publication_error: type[Exception],
    ) -> None:
        self.path = Path(path)
        self._fingerprint = str(catalog_fingerprint)
        self._as_of = _aware(as_of)
        self._publication_error = publication_error
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise publication_error("provider signal checkpoint exact path must not be a symlink")
        self.connection = self._open_or_reset()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA temp_store = FILE")
        connection.execute(f"PRAGMA cache_size = -{_SQLITE_CACHE_KIB}")
        connection.execute("PRAGMA mmap_size = 0")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _open_or_reset(self) -> sqlite3.Connection:
        if self.path.exists():
            connection = self._connect()
            if self._checkpoint_is_compatible(connection):
                return connection
            connection.close()
            _unlink_sqlite(self.path)

        connection = self._connect()
        connection.execute(
            "CREATE TABLE checkpoint_metadata ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL"
            ") WITHOUT ROWID"
        )
        connection.execute(
            "CREATE TABLE signals ("
            "symbol TEXT PRIMARY KEY, payload TEXT NOT NULL"
            ") WITHOUT ROWID"
        )
        connection.execute(
            "CREATE TABLE sources ("
            "ordinal INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source TEXT NOT NULL UNIQUE"
            ")"
        )
        connection.execute(
            "CREATE TABLE completed_exchanges ("
            "exchange TEXT PRIMARY KEY"
            ") WITHOUT ROWID"
        )
        metadata = {
            "schema_version": _CHECKPOINT_SCHEMA,
            "catalog_fingerprint": self._fingerprint,
            "origin_as_of": self._as_of.isoformat(),
        }
        connection.executemany(
            "INSERT INTO checkpoint_metadata(key, value) VALUES (?, ?)",
            tuple(metadata.items()),
        )
        connection.commit()
        return connection

    def _checkpoint_is_compatible(self, connection: sqlite3.Connection) -> bool:
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                return False
            rows = connection.execute(
                "SELECT key, value FROM checkpoint_metadata"
            ).fetchall()
            metadata = {str(key): str(value) for key, value in rows}
            if metadata.get("schema_version") != _CHECKPOINT_SCHEMA:
                return False
            if metadata.get("catalog_fingerprint") != self._fingerprint:
                return False
            origin_raw = metadata.get("origin_as_of")
            if not origin_raw:
                return False
            origin = _aware(datetime.fromisoformat(origin_raw.replace("Z", "+00:00")))
            age = (self._as_of - origin).total_seconds()
            if age < 0.0 or age > _MAX_CHECKPOINT_AGE_SECONDS:
                return False
            required = {"signals", "sources", "completed_exchanges"}
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            return required.issubset(tables)
        except (sqlite3.DatabaseError, TypeError, ValueError):
            return False

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "_DurableSignalStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def put(self, symbol: str, signal: Mapping[str, object]) -> None:
        payload = json.dumps(
            dict(signal),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO signals(symbol, payload) VALUES (?, ?)",
            (str(symbol), payload),
        )

    def contains(self, symbol: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM signals WHERE symbol = ? LIMIT 1",
            (str(symbol),),
        ).fetchone()
        return row is not None

    @property
    def signal_count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM signals").fetchone()
        return 0 if row is None else int(row[0])

    def iter_signals(self):
        cursor = self.connection.execute(
            "SELECT symbol, payload FROM signals ORDER BY symbol"
        )
        for symbol, payload in cursor:
            value = json.loads(str(payload))
            if not isinstance(value, Mapping):
                raise self._publication_error(
                    "provider signal checkpoint contains an invalid signal payload"
                )
            yield str(symbol), value

    def add_source(self, source: object) -> None:
        value = str(source).strip()
        if not value:
            return
        self.connection.execute(
            "INSERT OR IGNORE INTO sources(source) VALUES (?)", (value,)
        )

    def iter_sources(self):
        cursor = self.connection.execute(
            "SELECT source FROM sources ORDER BY ordinal"
        )
        for (source,) in cursor:
            yield str(source)

    def commit(self) -> None:
        self.connection.commit()

    def exchange_completed(self, exchange: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM completed_exchanges WHERE exchange = ? LIMIT 1",
            (str(exchange),),
        ).fetchone()
        return row is not None

    def mark_exchange_completed(self, exchange: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO completed_exchanges(exchange) VALUES (?)",
            (str(exchange),),
        )


class _PatchState:
    checkpoint_path: Path | None = None
    fingerprint: str | None = None
    as_of: datetime | None = None


def _install_publication_patch() -> None:
    from operations import bounded_provider_preselection_publication as publication

    if getattr(publication, "_resumable_exchange_checkpoint_installed", False):
        return

    original_store = publication._SignalStore
    original_insert_exchange = publication._insert_exchange_signals
    original_ensure = publication.ensure_provider_preselection_publication
    state = _PatchState()

    def store_factory():
        if state.checkpoint_path is None or state.fingerprint is None or state.as_of is None:
            return original_store()
        return _DurableSignalStore(
            state.checkpoint_path,
            catalog_fingerprint=state.fingerprint,
            as_of=state.as_of,
            publication_error=publication.ProviderPreselectionPublicationError,
        )

    def insert_exchange(store, *, exchange, members, as_of, api_token, http_get):
        if isinstance(store, _DurableSignalStore) and store.exchange_completed(exchange):
            return None
        result = original_insert_exchange(
            store,
            exchange=exchange,
            members=members,
            as_of=as_of,
            api_token=api_token,
            http_get=http_get,
        )
        if result is None and isinstance(store, _DurableSignalStore):
            store.mark_exchange_completed(exchange)
            # Durability is established exchange-by-exchange so SIGTERM at the unchanged
            # fanout deadline cannot discard already completed provider work.
            store.commit()
        return result

    def ensure(catalogs, *, as_of, policy=None, http_get=publication._core.requests.get, market_probe=None):
        resolved = policy or publication.ComprehensiveMarketDiscoveryPolicy()
        raw_path = getattr(resolved, "provider_preselection_path", None)
        if not raw_path:
            return original_ensure(
                catalogs,
                as_of=as_of,
                policy=policy,
                http_get=http_get,
                market_probe=market_probe,
            )
        fingerprint = publication.provider_preselection_catalog_fingerprint(catalogs)
        previous = (state.checkpoint_path, state.fingerprint, state.as_of)
        state.checkpoint_path = _checkpoint_path(Path(str(raw_path)).expanduser())
        state.fingerprint = fingerprint
        state.as_of = _aware(as_of)
        try:
            return original_ensure(
                catalogs,
                as_of=as_of,
                policy=policy,
                http_get=http_get,
                market_probe=market_probe,
            )
        finally:
            state.checkpoint_path, state.fingerprint, state.as_of = previous

    publication._SignalStore = store_factory
    publication._insert_exchange_signals = insert_exchange
    publication.ensure_provider_preselection_publication = ensure
    publication._resumable_exchange_checkpoint_installed = True


def install_for_epoch_provider_child(argv: tuple[str, ...] | None = None) -> bool:
    """Install the checkpoint patch only in the exact provider-acquisition child."""

    if not _is_epoch_provider_child(argv):
        return False
    _install_publication_patch()
    return True


__all__ = [
    "_CHECKPOINT_SCHEMA",
    "_DurableSignalStore",
    "_MAX_CHECKPOINT_AGE_SECONDS",
    "_checkpoint_path",
    "_is_epoch_provider_child",
    "install_for_epoch_provider_child",
]
