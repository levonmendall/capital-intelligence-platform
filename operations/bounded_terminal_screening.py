"""CIO #440 storage-bound compatibility layer.

The certified terminal-screening implementation is preserved verbatim in
``_bounded_terminal_screening_core.py``.  This module executes that implementation in
the public module namespace, then applies only resource-lifecycle controls proven
necessary by production diagnostic #440:

* compact a very large publication-wide source list to one content-addressed manifest
  identifier before it is copied into per-instrument evidence;
* disable rollback journals for disposable terminal-screening SQLite scratch databases;
* make the existing storage reserve metric transaction-aware by retaining the largest
  observed chunk growth as the next-chunk budget.

No catalog membership, screening rule, factor requirement, ranking, threshold,
portfolio authority, execution behavior, or paper-only control is changed.
"""
from __future__ import annotations

from pathlib import Path as _Path

_core_path = _Path(__file__).with_name("_bounded_terminal_screening_core.py")
_core_source = _core_path.read_text(encoding="utf-8")
exec(compile(_core_source, str(_core_path), "exec"), globals(), globals())
del _core_source

import hashlib as _hashlib

_PUBLICATION_SOURCE_INLINE_LIMIT_BYTES = 64 * 1024
_DYNAMIC_STORAGE_HEADROOM_BYTES = 16 * 1024 * 1024
_DYNAMIC_STORAGE_GROWTH_MULTIPLIER = 4
_screening_spool_growth: dict[str, tuple[int, int]] = {}

_core_configure_spool_connection = _configure_spool_connection
_core_publication_spool_init = _PublicationSignalSpool.__init__
_core_storage_metrics = _storage_metrics


def _configure_spool_connection(connection: sqlite3.Connection) -> None:
    """Configure bounded scratch SQLite without transient rollback-file duplication."""
    _core_configure_spool_connection(connection)
    # Both terminal SQLite databases are disposable derived state.  An interrupted run
    # fails closed and rebuilds them from the immutable canonical publication, so a
    # rollback journal only duplicates scratch pages and can consume the Render
    # filesystem without adding durable recovery value.
    connection.execute("PRAGMA journal_mode = OFF")


def _publication_source_manifest_identifier(values: object) -> str | None:
    """Return a content-addressed identifier when global lineage is too large to inline."""
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return None
    normalized = tuple(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )
    if not normalized:
        return None
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(serialized) <= _PUBLICATION_SOURCE_INLINE_LIMIT_BYTES:
        return None
    digest = _hashlib.sha256(serialized).hexdigest()
    return (
        "provider-publication-source-manifest:"
        f"sha256:{digest}:count:{len(normalized)}"
    )


def _bounded_publication_spool_init(self, publication_path: Path) -> None:
    _core_publication_spool_init(self, publication_path)
    manifest_identifier = _publication_source_manifest_identifier(
        self.metadata.get("source_identifiers", ())
    )
    if manifest_identifier is not None:
        # The canonical publication remains unchanged and therefore remains the exact
        # point-in-time manifest.  Per-signal/factor lineage is still retained verbatim;
        # only the publication-wide list that would otherwise be copied into every one
        # of 45k+ screening rows is represented by its immutable SHA-256 identifier.
        self.metadata["source_identifiers"] = (manifest_identifier,)


_PublicationSignalSpool.__init__ = _bounded_publication_spool_init


def _storage_metrics(
    *,
    publication_path: Path,
    publication_index_path: Path,
    screening_spool_path: Path,
    chunk_path: Path | None = None,
) -> dict[str, int]:
    """Add a next-transaction budget without introducing new telemetry field names."""
    metrics = _core_storage_metrics(
        publication_path=publication_path,
        publication_index_path=publication_index_path,
        screening_spool_path=screening_spool_path,
        chunk_path=chunk_path,
    )
    current_size = int(metrics.get("screening_spool_bytes", 0))
    key = str(screening_spool_path)
    previous_size, peak_growth = _screening_spool_growth.get(
        key, (current_size, 0)
    )
    observed_growth = max(0, current_size - previous_size)
    peak_growth = max(peak_growth, observed_growth)
    _screening_spool_growth[key] = (current_size, peak_growth)

    base_reserve = int(metrics.get("storage_reserve_bytes", 0))
    transaction_budget = (
        _DYNAMIC_STORAGE_HEADROOM_BYTES
        + _DYNAMIC_STORAGE_GROWTH_MULTIPLIER * peak_growth
    )
    metrics["storage_reserve_bytes"] = max(base_reserve, transaction_budget)
    return metrics


del _Path
