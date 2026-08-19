"""Build the smallest governed universe that must stay operational continuously.

Comprehensive discovery expands future opportunity coverage.  This module instead resolves
what the CIO is already allowed to evaluate now: the bootstrap paper universe, exact active
instrument capability certifications from the latest publication, and owned instruments
that require monitoring/exit continuity.  It performs no provider discovery and grants no
new capability authority.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.active_paper_universe import load_active_paper_universe_for_publication
from operations.free_paper_pilot import (
    FreePaperPilotUniverse,
    _free_paper_pilot_universe_from_payload,
    active_paper_universe_path,
    load_free_paper_pilot_universe,
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)


def _candidate_paths() -> tuple[Path, ...]:
    values = [active_paper_universe_path()]
    data_dir = os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if data_dir:
        values.append(Path(data_dir).expanduser() / "active-paper-universe.json")
    portfolio_database = os.getenv(
        "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE", ""
    ).strip()
    if portfolio_database:
        values.append(
            Path(portfolio_database).expanduser().with_name("active-paper-universe.json")
        )
    return tuple(dict.fromkeys(values))


def _load_active_publication() -> tuple[Path, str, FreePaperPilotUniverse] | None:
    for path in _candidate_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        identifier = str(
            payload.get("eligible_universe_publication_identifier") or ""
        ).strip()
        universe_payload = payload.get("universe")
        if not identifier or not isinstance(universe_payload, Mapping):
            continue
        try:
            universe = _free_paper_pilot_universe_from_payload(universe_payload)
        except (KeyError, TypeError, ValueError):
            continue
        return path, identifier, universe
    return None


def load_current_authorized_universe(*, as_of: datetime) -> FreePaperPilotUniverse | None:
    """Return exact currently authorized members of the latest active publication."""

    evaluated_at = _aware(as_of)
    active = _load_active_publication()
    if active is None:
        return None
    path, publication_identifier, _raw = active
    try:
        return load_active_paper_universe_for_publication(
            publication_identifier,
            path=path,
            evaluated_at=evaluated_at,
        )
    except (OSError, TypeError, ValueError):
        return None


def build_capability_operating_universe(
    *,
    as_of: datetime,
    held_symbols: Sequence[str] = (),
) -> tuple[FreePaperPilotUniverse, tuple[str, ...]]:
    """Resolve current allocation scope plus mandatory held-instrument evidence scope."""

    evaluated_at = _aware(as_of)
    base = load_free_paper_pilot_universe()
    base_ids = {item.instrument_identifier for item in base.instruments}
    base_symbols = {item.symbol for item in base.instruments}
    held = tuple(
        sorted({str(symbol).strip().upper() for symbol in held_symbols if str(symbol).strip()})
    )

    active = _load_active_publication()
    authorized = load_current_authorized_universe(as_of=evaluated_at)
    authorized_instruments = () if authorized is None else authorized.instruments
    authorized_ids = {item.instrument_identifier for item in authorized_instruments}

    raw_active = None if active is None else active[2]
    raw_by_symbol = (
        {}
        if raw_active is None
        else {item.symbol: item for item in raw_active.instruments}
    )
    unresolved_holdings = tuple(
        symbol
        for symbol in held
        if symbol not in base_symbols and symbol not in raw_by_symbol
    )
    if unresolved_holdings:
        raise ValueError(
            "canonical holdings cannot be resolved to the active instrument publication: "
            + ", ".join(unresolved_holdings)
        )

    selected = list(base.instruments)
    selected_ids = set(base_ids)
    for item in authorized_instruments:
        if item.instrument_identifier not in selected_ids:
            selected.append(item)
            selected_ids.add(item.instrument_identifier)

    holding_only: list[str] = []
    for symbol in held:
        item = raw_by_symbol.get(symbol)
        if item is None or item.instrument_identifier in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.instrument_identifier)
        if item.instrument_identifier not in authorized_ids:
            holding_only.append(symbol)

    publication_identifier = "none" if active is None else active[1]
    universe = replace(
        base,
        identifier=(
            f"capability-operating:{evaluated_at.strftime('%Y%m%dT%H%M%S%fZ')}:"
            f"{publication_identifier}"
        ),
        objective=(
            base.objective
            + " Current active capability-certified instruments compete for capital; "
            "comprehensive discovery expands this operating set asynchronously."
        ),
        instruments=tuple(selected),
        limitations=tuple(
            dict.fromkeys(
                (
                    *base.limitations,
                    "Operating membership is limited to bootstrap authority, exact current instrument capability certifications, and evidence-only continuity for canonical holdings.",
                    "Comprehensive all-market discovery has no authority to block this already-certified operating set.",
                    "Owned instruments whose current allocation capability is suspended remain evidence-only for monitoring and reduction/exit continuity.",
                )
            )
        ),
    )
    return universe, tuple(sorted(holding_only))


__all__ = [
    "build_capability_operating_universe",
    "load_current_authorized_universe",
]
