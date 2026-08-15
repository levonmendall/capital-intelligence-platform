"""Deterministically reconstruct the instrument scope owned by evidence collection.

This helper consumes only already-qualified discovery snapshots and the last certified
active universe for mandatory holding continuity.  It performs no provider I/O and has no
candidate, CIO, construction, sizing, execution, or real-money authority.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Mapping, Sequence

from operations.equity_discovery_snapshot import (
    load_equity_discovery_snapshot,
    view_equity_discovery_snapshot,
)
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_current_active_paper_universe,
    load_free_paper_pilot_universe,
)
from operations.qualified_comprehensive_discovery_snapshot import (
    load_qualified_comprehensive_discovery_snapshot,
    view_qualified_comprehensive_discovery_snapshot,
)


def _symbols(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip().upper() for item in values if str(item).strip()}))


def build_evidence_collection_universe(
    *,
    evidence_as_of: datetime,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    values: Mapping[str, str],
):
    """Return the exact discovery-derived instrument scope plus holding continuity."""

    held = _symbols(held_symbols)
    tracked = _symbols(tracked_symbols)
    base = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
    base_symbols = tuple(sorted(base.symbol_map))

    equity_snapshot = load_equity_discovery_snapshot(
        evidence_as_of=evidence_as_of,
        values=values,
    )
    equity = view_equity_discovery_snapshot(
        equity_snapshot,
        held_symbols=held,
        tracked_symbols=tracked,
        excluded_symbols=base_symbols,
    )
    equity_instruments = equity.instruments_for_holdings(held)

    global_snapshot = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=evidence_as_of,
        values=values,
    )
    comprehensive = view_qualified_comprehensive_discovery_snapshot(
        global_snapshot,
        held_symbols=held,
        tracked_symbols=tracked,
        excluded_symbols=tuple(
            (*base_symbols, *(item.symbol for item in equity_instruments))
        ),
    )
    comprehensive_instruments = comprehensive.instruments_for_holdings(held)

    combined = tuple((*base.instruments, *equity_instruments, *comprehensive_instruments))
    combined_symbols = {item.symbol for item in combined}
    missing_holdings = tuple(symbol for symbol in held if symbol not in combined_symbols)
    carried = ()
    if missing_holdings:
        _publication_id, prior = load_current_active_paper_universe()
        prior_by_symbol = prior.symbol_map
        unresolved = tuple(symbol for symbol in missing_holdings if symbol not in prior_by_symbol)
        if unresolved:
            raise ValueError(
                "canonical holdings cannot be reconciled to certified instrument metadata: "
                + ", ".join(unresolved)
            )
        carried = tuple(prior_by_symbol[symbol] for symbol in missing_holdings)

    universe = replace(
        base,
        identifier=(
            f"evidence-collection:{equity_snapshot.snapshot_id}:"
            f"{global_snapshot.snapshot_id}"
        ),
        instruments=tuple((*combined, *carried)),
        limitations=tuple(
            dict.fromkeys(
                (
                    *base.limitations,
                    "Evidence collection scope is reconstructed only from immutable qualified discovery snapshots.",
                    *(
                        ()
                        if not carried
                        else (
                            "Canonical holdings omitted by fresh discovery retain mandatory evidence-only monitoring from the last certified active universe.",
                        )
                    ),
                )
            )
        ),
    )
    return universe, missing_holdings


__all__ = ["build_evidence_collection_universe"]
