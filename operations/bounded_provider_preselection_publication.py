"""Bound provider-factor publication memory without changing discovery semantics.

The canonical provider-preselection runtime builds a complete in-memory signal mapping and
then materializes a second complete JSON string before writing it. Large equity-like lanes
can therefore cross the production memory boundary even though comprehensive discovery is
already isolated by asset class.

This module preserves the same catalog fingerprint, provider observations, factor scoring,
crypto compatibility fallback, freshness rules, and paper-only authority contract while
spooling normalized signals to SQLite and writing the canonical pretty-JSON shape one
signal at a time. Exchange bulk snapshots are processed serially so no worker retains raw
rows from multiple exchanges concurrently. Transient exchange-bulk failures are retried
only for the failed exchanges inside the same already-bounded provider child; successful
exchange work remains in the disk-backed store, and persistent or entitlement failures
remain explicit limitations that the exact-epoch publication owner refuses to promote.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from cio import CandidateAssetClass
from operations import _provider_preselection_publication_runtime_core as _core
from operations import provider_preselection_publication_runtime as _runtime
from operations._bounded_terminal_screening_core import _PublicationSignalSpool


ProviderPreselectionPublicationError = _core.ProviderPreselectionPublicationError
ProviderPreselectionPublicationResult = _core.ProviderPreselectionPublicationResult
ComprehensiveMarketDiscoveryPolicy = _core.ComprehensiveMarketDiscoveryPolicy
DiscoveryCatalogRecord = _core.DiscoveryCatalogRecord
DiscoveryMarketFeatures = _core.DiscoveryMarketFeatures

_SQLITE_CACHE_KIB = 2048
_BULK_RETRY_ROUNDS = 2
_BULK_RETRY_SLEEP_SECONDS = 0.5


class _SignalStore:
    """Disk-backed normalized provider signals with deterministic iteration."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="cio-provider-preselection-"
        )
        self.path = Path(self._temporary.name) / "signals.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA temp_store = FILE")
        self.connection.execute(f"PRAGMA cache_size = -{_SQLITE_CACHE_KIB}")
        self.connection.execute("PRAGMA mmap_size = 0")
        self.connection.execute("PRAGMA journal_mode = OFF")
        self.connection.execute(
            "CREATE TABLE signals ("
            "symbol TEXT PRIMARY KEY, payload TEXT NOT NULL"
            ") WITHOUT ROWID"
        )
        self.connection.execute(
            "CREATE TABLE sources ("
            "ordinal INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source TEXT NOT NULL UNIQUE"
            ")"
        )

    def close(self) -> None:
        try:
            self.connection.close()
        finally:
            self._temporary.cleanup()

    def __enter__(self) -> "_SignalStore":
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

    def iter_signals(self) -> Iterator[tuple[str, Mapping[str, object]]]:
        cursor = self.connection.execute(
            "SELECT symbol, payload FROM signals ORDER BY symbol"
        )
        for symbol, payload in cursor:
            value = json.loads(str(payload))
            if not isinstance(value, Mapping):
                raise ProviderPreselectionPublicationError(
                    "bounded provider signal spool contains an invalid payload"
                )
            yield str(symbol), value

    def add_source(self, source: object) -> None:
        value = str(source).strip()
        if not value:
            return
        self.connection.execute(
            "INSERT OR IGNORE INTO sources(source) VALUES (?)", (value,)
        )

    def iter_sources(self) -> Iterator[str]:
        cursor = self.connection.execute(
            "SELECT source FROM sources ORDER BY ordinal"
        )
        for (source,) in cursor:
            yield str(source)

    def commit(self) -> None:
        self.connection.commit()


def _records_for_lane(
    catalogs: Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]],
) -> tuple[DiscoveryCatalogRecord, ...]:
    """Preserve canonical flattening for a single already-deduplicated lane."""

    values: list[DiscoveryCatalogRecord] = []
    seen: set[tuple[CandidateAssetClass, str]] = set()
    for asset_class, records in catalogs.items():
        if not isinstance(asset_class, CandidateAssetClass):
            continue
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise ProviderPreselectionPublicationError(
                f"{asset_class.value} catalog must be a sequence"
            )
        for record in records:
            if not isinstance(record, DiscoveryCatalogRecord):
                raise ProviderPreselectionPublicationError(
                    f"{asset_class.value} catalog contains an invalid record"
                )
            key = (record.asset_class, record.symbol)
            if key in seen:
                # Canonical flattening is last-record-wins. The lane spool is already
                # deduplicated, so encountering this is exceptional; preserve the rule
                # without creating a full catalog dictionary in the normal path.
                values = [
                    item
                    for item in values
                    if (item.asset_class, item.symbol) != key
                ]
            seen.add(key)
            values.append(record)
    values.sort(key=lambda item: (item.asset_class.value, item.symbol))
    return tuple(values)


def _streaming_catalog_fingerprint(
    records: Sequence[DiscoveryCatalogRecord],
) -> str:
    """Produce the exact canonical catalog fingerprint without a tuple-list copy."""

    import hashlib

    digest = hashlib.sha256()
    digest.update(b"[")
    for index, item in enumerate(records):
        if index:
            digest.update(b",")
        payload = (
            item.asset_class.value,
            item.symbol,
            item.provider_symbol,
            item.source_identifier,
        )
        digest.update(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
                default=str,
            ).encode("utf-8")
        )
    digest.update(b"]")
    return digest.hexdigest()


def _existing_result_bounded(
    path: Path,
    *,
    as_of: datetime,
    fingerprint: str,
    catalog_count: int,
    freshness_days: int,
) -> ProviderPreselectionPublicationResult | None:
    """Validate a reusable publication without loading its complete signal map."""

    if not path.exists():
        return None
    try:
        with _PublicationSignalSpool(path) as spool:
            metadata = spool.metadata
            if metadata.get("schema_version") != _core.PROVIDER_PRESELECTION_SCHEMA:
                return None
            if metadata.get("catalog_fingerprint") != fingerprint:
                return None
            available_at = _core._parse_timestamp(metadata.get("available_at"))
            if available_at is None or available_at > as_of:
                return None
            if (as_of - available_at).total_seconds() > freshness_days * 86_400:
                return None
            if spool.signal_count < 1:
                return None
            sources = metadata.get("source_identifiers", ())
            limitations = metadata.get("limitations", ())
            return ProviderPreselectionPublicationResult(
                path=path,
                available_at=available_at,
                catalog_count=catalog_count,
                signal_count=spool.signal_count,
                reused=True,
                source_identifiers=tuple(
                    str(item)
                    for item in sources
                    if isinstance(item, str) and item.strip()
                ),
                limitations=tuple(
                    str(item)
                    for item in limitations
                    if isinstance(item, str) and item.strip()
                ),
            )
    except Exception:
        return None


def _insert_exchange_signals(
    store: _SignalStore,
    *,
    exchange: str,
    members: Sequence[tuple[DiscoveryCatalogRecord, str]],
    as_of: datetime,
    api_token: str,
    http_get: Callable[..., Any],
) -> str | None:
    """Collect and release one exchange snapshot before advancing to the next."""

    try:
        rows, observed_at, evidence_identifier = _core._bulk_snapshot(
            exchange,
            as_of=as_of,
            api_token=api_token,
            http_get=http_get,
        )
    except ProviderPreselectionPublicationError as error:
        return str(error)

    by_code: dict[str, Mapping[str, object]] = {}
    for row in rows:
        for key in _core._row_keys(row):
            by_code.setdefault(key, row)
    del rows

    for record, code in members:
        candidates = (
            code,
            code.split(".", 1)[0],
            record.provider_symbol.upper(),
            record.provider_symbol.upper().split(".", 1)[0],
        )
        row = next(
            (by_code[key] for key in dict.fromkeys(candidates) if key in by_code),
            None,
        )
        if row is None:
            continue
        signal = _core._bulk_signal(
            record,
            row,
            observed_at=observed_at,
            evidence_identifier=evidence_identifier,
        )
        if signal is not None:
            store.put(record.symbol, signal)
    store.add_source(evidence_identifier)
    return None


def _bulk_error_retryable(error_detail: str) -> bool:
    """Retry transient exchange acquisition, never entitlement failures."""

    normalized = str(error_detail or "").strip().lower()
    if not normalized:
        return False
    return not (
        "entitlement is unavailable" in normalized
        or "http 401" in normalized
        or "http 403" in normalized
    )


def _collect_exchange_signals_with_retries(
    store: _SignalStore,
    *,
    grouped: Mapping[str, Sequence[tuple[DiscoveryCatalogRecord, str]]],
    as_of: datetime,
    api_token: str,
    http_get: Callable[..., Any],
) -> tuple[str, ...]:
    """Retry only failed exchanges without re-fetching successful exchange snapshots.

    The provider child is still terminated by the existing exact-epoch fanout deadline, so
    these retries cannot extend the 300-second acceleration ceiling or consume the 480-second
    downstream reserve. An exchange is removed from the limitation set only after the same
    canonical bulk collector succeeds; persistent and entitlement failures remain explicit.
    """

    pending = {str(exchange): tuple(members) for exchange, members in grouped.items()}
    failures: dict[str, str] = {}

    for round_index in range(_BULK_RETRY_ROUNDS + 1):
        if not pending:
            break
        next_pending: dict[str, tuple[tuple[DiscoveryCatalogRecord, str], ...]] = {}
        for exchange in sorted(pending):
            error_detail = _insert_exchange_signals(
                store,
                exchange=exchange,
                members=pending[exchange],
                as_of=as_of,
                api_token=api_token,
                http_get=http_get,
            )
            if error_detail is None:
                failures.pop(exchange, None)
                continue
            failures[exchange] = error_detail
            if round_index < _BULK_RETRY_ROUNDS and _bulk_error_retryable(error_detail):
                next_pending[exchange] = pending[exchange]

        if next_pending and round_index < _BULK_RETRY_ROUNDS:
            _runtime.record_manual_cio_diagnostic_progress(
                "provider_preselection_bulk_retry",
                metrics={
                    "retry_round": round_index + 1,
                    "failed_exchanges": len(next_pending),
                },
            )
            store.commit()
            time.sleep(_BULK_RETRY_SLEEP_SECONDS)
        pending = next_pending

    return tuple(failures[exchange] for exchange in sorted(failures))


def _provider_features(
    records: Sequence[DiscoveryCatalogRecord],
    *,
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy,
    market_probe,
    crypto_compatibility: bool,
) -> tuple[Mapping[str, DiscoveryMarketFeatures], tuple[str, ...]]:
    if crypto_compatibility:
        return _runtime._provider_history_features(
            records,
            as_of=as_of,
            policy=policy,
            market_probe=market_probe,
        )

    _runtime.record_manual_cio_diagnostic_progress(
        "provider_preselection_fallback_probe",
        metrics={"catalog_records": len(records)},
    )
    limitations: list[str] = []
    try:
        if market_probe is not None:
            features = market_probe(records, as_of, policy)
        else:
            features = _runtime.default_market_probe(
                records,
                as_of,
                policy,
                maximum_workers=1,
            )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        limitations.append(
            "provider-native derivative/alternate factor probe failed: "
            f"{type(error).__name__}"
        )
        features = {}
    _runtime.record_manual_cio_diagnostic_progress(
        "provider_preselection_fallback_probe_complete",
        metrics={"evidence_complete_records": len(features)},
    )
    return features, tuple(limitations)


def _insert_history_signals(
    store: _SignalStore,
    records: Sequence[DiscoveryCatalogRecord],
    *,
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy,
    market_probe,
    crypto_compatibility: bool,
) -> tuple[int, tuple[str, ...]]:
    if not records:
        return 0, ()
    features, limitations = _provider_features(
        records,
        as_of=as_of,
        policy=policy,
        market_probe=market_probe,
        crypto_compatibility=crypto_compatibility,
    )
    inserted = 0
    for record in records:
        item = features.get(record.symbol)
        if item is None:
            continue
        store.put(record.symbol, _core._feature_signal(record, item))
        for source in item.evidence_identifiers:
            store.add_source(source)
        inserted += 1
    return inserted, limitations


def _write_indented_value(handle, value: object, *, indent: int) -> None:
    encoded = json.dumps(
        value,
        indent=2,
        sort_keys=True,
        allow_nan=False,
        default=str,
    ).splitlines()
    if not encoded:
        handle.write("null")
        return
    handle.write(encoded[0])
    prefix = " " * indent
    for line in encoded[1:]:
        handle.write("\n")
        handle.write(prefix)
        handle.write(line)


def _write_signals(handle, store: _SignalStore) -> None:
    handle.write("{\n")
    total = store.signal_count
    for index, (symbol, signal) in enumerate(store.iter_signals()):
        handle.write("    ")
        handle.write(json.dumps(symbol))
        handle.write(": ")
        _write_indented_value(handle, signal, indent=4)
        if index + 1 < total:
            handle.write(",")
        handle.write("\n")
    handle.write("  }")


def _write_sources(handle, store: _SignalStore) -> None:
    handle.write("[\n")
    sources = store.connection.execute("SELECT COUNT(*) FROM sources").fetchone()
    total = 0 if sources is None else int(sources[0])
    for index, source in enumerate(store.iter_sources()):
        handle.write("    ")
        handle.write(json.dumps(source))
        if index + 1 < total:
            handle.write(",")
        handle.write("\n")
    handle.write("  ]")


def _atomic_stream_publication(
    path: Path,
    *,
    metadata: Mapping[str, object],
    store: _SignalStore,
) -> None:
    """Write the canonical top-level shape without materializing all signals."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    keys = sorted((*metadata.keys(), "signals", "source_identifiers"))
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write("{\n")
        for index, key in enumerate(keys):
            handle.write("  ")
            handle.write(json.dumps(key))
            handle.write(": ")
            if key == "signals":
                _write_signals(handle, store)
            elif key == "source_identifiers":
                _write_sources(handle, store)
            else:
                _write_indented_value(handle, metadata[key], indent=2)
            if index + 1 < len(keys):
                handle.write(",")
            handle.write("\n")
        handle.write("}\n")
    temporary.replace(path)


def verify_provider_preselection_publication(
    catalogs: Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]],
    *,
    publication: ProviderPreselectionPublicationResult,
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
    expected_path: str | Path | None = None,
) -> ProviderPreselectionPublicationResult:
    """Re-open the exact publication and fail closed unless its durable shape survives."""

    timestamp = _core._aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    records = _records_for_lane(catalogs)
    if not records:
        raise ProviderPreselectionPublicationError(
            "provider publication verification requires a nonempty catalog"
        )
    fingerprint = _streaming_catalog_fingerprint(records)
    path = (
        Path(expected_path).expanduser()
        if expected_path is not None
        else _core._publication_path(resolved)
    )
    actual = Path(publication.path).expanduser()
    if actual.resolve(strict=False) != path.resolve(strict=False):
        raise ProviderPreselectionPublicationError(
            "bounded provider publication escaped its exact requested path"
        )
    if path.is_symlink():
        raise ProviderPreselectionPublicationError(
            "bounded provider publication exact path must not be a symlink"
        )
    if int(publication.catalog_count) != len(records):
        raise ProviderPreselectionPublicationError(
            "bounded provider publication catalog count changed before verification"
        )
    return verify_provider_preselection_artifact(
        path,
        as_of=timestamp,
        fingerprint=fingerprint,
        catalog_count=len(records),
        signal_count=int(publication.signal_count),
        available_at=publication.available_at,
        freshness_days=int(getattr(resolved, "preselection_freshness_days", 3)),
    )


def verify_provider_preselection_artifact(
    path: str | Path,
    *,
    as_of: datetime,
    fingerprint: str,
    catalog_count: int,
    signal_count: int,
    available_at: datetime,
    freshness_days: int,
) -> ProviderPreselectionPublicationResult:
    """Verify one exact publication from compact transaction metadata only."""

    target = Path(path).expanduser()
    if target.is_symlink():
        raise ProviderPreselectionPublicationError(
            "bounded provider publication exact path must not be a symlink"
        )
    verified = _existing_result_bounded(
        target,
        as_of=_core._aware(as_of, field_name="as_of"),
        fingerprint=str(fingerprint),
        catalog_count=int(catalog_count),
        freshness_days=int(freshness_days),
    )
    if verified is None:
        raise ProviderPreselectionPublicationError(
            "bounded provider publication failed durable exact-path readback verification"
        )
    if int(verified.catalog_count) != int(catalog_count):
        raise ProviderPreselectionPublicationError(
            "bounded provider publication catalog count changed before verification"
        )
    if int(verified.signal_count) != int(signal_count):
        raise ProviderPreselectionPublicationError(
            "bounded provider publication signal count changed during durable readback"
        )
    expected_available = _core._aware(available_at, field_name="available_at")
    if verified.available_at != expected_available:
        raise ProviderPreselectionPublicationError(
            "bounded provider publication availability timestamp changed during readback"
        )
    return verified


def provider_preselection_catalog_fingerprint(
    catalogs: Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]],
) -> str:
    """Return the canonical compact fingerprint used by durable publication readback."""

    records = _records_for_lane(catalogs)
    if not records:
        raise ProviderPreselectionPublicationError(
            "provider publication fingerprint requires a nonempty catalog"
        )
    return _streaming_catalog_fingerprint(records)


def ensure_provider_preselection_publication(
    catalogs: Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]],
    *,
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
    http_get=_core.requests.get,
    market_probe=None,
) -> ProviderPreselectionPublicationResult:
    """Build/reuse the governed provider publication under a bounded signal lifetime."""

    _runtime._sync_core_overrides()
    timestamp = _core._aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    records = _records_for_lane(catalogs)
    if not records:
        raise ProviderPreselectionPublicationError(
            "provider preselection publication requires a nonempty catalog"
        )
    fingerprint = _streaming_catalog_fingerprint(records)
    path = _core._publication_path(resolved)
    freshness_days = int(getattr(resolved, "preselection_freshness_days", 3))
    existing = _existing_result_bounded(
        path,
        as_of=timestamp,
        fingerprint=fingerprint,
        catalog_count=len(records),
        freshness_days=freshness_days,
    )
    if existing is not None:
        return existing

    grouped: dict[str, list[tuple[DiscoveryCatalogRecord, str]]] = {}
    fallback_records: list[DiscoveryCatalogRecord] = []
    grouped_crypto: list[DiscoveryCatalogRecord] = []
    for record in records:
        identity = _core._source_exchange_and_code(record)
        if identity is None:
            fallback_records.append(record)
            continue
        exchange, code = identity
        grouped.setdefault(exchange, []).append((record, code))
        if record.asset_class is CandidateAssetClass.CRYPTO:
            grouped_crypto.append(record)

    limitations: list[str] = []
    api_token = (
        os.getenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN")
        or os.getenv("EODHD_API_TOKEN")
        or ""
    ).strip()

    with _SignalStore() as store:
        if grouped and not api_token:
            limitations.append(
                "EODHD bulk factor publication was not attempted because its API token "
                "is unavailable."
            )
        if api_token and grouped:
            _runtime.record_manual_cio_diagnostic_progress(
                "provider_preselection_bulk_snapshots",
                metrics={"configured_exchanges": len(grouped)},
            )
            limitations.extend(
                _collect_exchange_signals_with_retries(
                    store,
                    grouped=grouped,
                    as_of=timestamp,
                    api_token=api_token,
                    http_get=http_get,
                )
            )
            store.commit()
            _runtime.record_manual_cio_diagnostic_progress(
                "provider_preselection_bulk_snapshots_complete",
                metrics={"evidence_complete_records": store.signal_count},
            )

        probe_records = tuple(
            item for item in fallback_records if not store.contains(item.symbol)
        )
        _inserted, fallback_limitations = _insert_history_signals(
            store,
            probe_records,
            as_of=timestamp,
            policy=resolved,
            market_probe=market_probe,
            crypto_compatibility=False,
        )
        limitations.extend(fallback_limitations)
        del probe_records

        unresolved_crypto = tuple(
            record for record in grouped_crypto if not store.contains(record.symbol)
        )
        crypto_inserted, crypto_limitations = _insert_history_signals(
            store,
            unresolved_crypto,
            as_of=timestamp,
            policy=resolved,
            market_probe=market_probe,
            crypto_compatibility=True,
        )
        limitations.extend(crypto_limitations)
        if crypto_inserted:
            limitations.append(
                "EODHD exchange-bulk evidence did not yield a substantive factor signal "
                f"for {crypto_inserted} crypto record(s); bounded provider-native "
                "history supplied the missing provider factors."
            )
        del unresolved_crypto
        store.commit()

        if store.signal_count < 1:
            raise ProviderPreselectionPublicationError(
                "no substantive provider factor signal could be produced for any "
                "certified market catalog record"
            )

        runtime_source = (
            f"provider-preselection-runtime:{_core._PUBLICATION_METHOD_VERSION}:"
            f"{fingerprint}"
        )
        # Match canonical ordering: the runtime source precedes provider evidence.
        existing_sources = tuple(store.iter_sources())
        store.connection.execute("DELETE FROM sources")
        store.connection.execute(
            "DELETE FROM sqlite_sequence WHERE name = 'sources'"
        )
        store.add_source(runtime_source)
        for source in existing_sources:
            if source != runtime_source:
                store.add_source(source)
        store.commit()

        unique_limitations = tuple(dict.fromkeys(str(item) for item in limitations))
        metadata: dict[str, object] = {
            "schema_version": _core.PROVIDER_PRESELECTION_SCHEMA,
            "methodology_version": _core._PUBLICATION_METHOD_VERSION,
            "available_at": timestamp.isoformat(),
            "catalog_fingerprint": fingerprint,
            "catalog_count": len(records),
            "signal_count": store.signal_count,
            "limitations": list(unique_limitations),
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
        _atomic_stream_publication(path, metadata=metadata, store=store)
        source_identifiers = tuple(store.iter_sources())
        result = ProviderPreselectionPublicationResult(
            path=path,
            available_at=timestamp,
            catalog_count=len(records),
            signal_count=store.signal_count,
            reused=False,
            source_identifiers=source_identifiers,
            limitations=unique_limitations,
        )
        verify_provider_preselection_publication(
            catalogs,
            publication=result,
            as_of=timestamp,
            policy=resolved,
            expected_path=path,
        )
        return result


__all__ = [
    "ProviderPreselectionPublicationError",
    "ProviderPreselectionPublicationResult",
    "ensure_provider_preselection_publication",
    "provider_preselection_catalog_fingerprint",
    "verify_provider_preselection_artifact",
    "verify_provider_preselection_publication",
]
