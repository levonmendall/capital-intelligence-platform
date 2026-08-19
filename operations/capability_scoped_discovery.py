"""Operational discovery boundary for the capability-scoped CIO runtime.

The all-market discovery/certification plane remains responsible for expanding global
coverage. The canonical CIO operating path must not wait for every market family to
re-certify simultaneously. This adapter carries forward only instruments that satisfy
three independent facts at the current decision timestamp:

* they were in the most recent active paper publication;
* their exact paper-allocation capability authority is still active; and
* the same exact instrument contract exists in the current immutable evidence snapshot.

It performs no provider discovery, creates no certification, and has no investment or
execution authority. Missing capability or evidence blocks only the affected instrument.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from operations.active_paper_universe import load_active_paper_universe_for_publication
from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
)
from operations.evidence_collection_universe import build_evidence_collection_universe
from operations.evidence_state_scope import load_evidence_state_scope
from operations.free_paper_pilot import (
    active_paper_universe_path,
    free_paper_pilot_universe_payload,
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)


def _publication_identifier(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    value = str(payload.get("eligible_universe_publication_identifier") or "").strip()
    return value or None


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


def _current_publication_source() -> tuple[Path | None, str | None]:
    for path in _candidate_paths():
        identifier = _publication_identifier(path)
        if identifier is not None:
            return path, identifier
    return None, None


def _instrument_contracts(universe) -> dict[str, dict[str, object]]:
    payload = free_paper_pilot_universe_payload(universe)
    raw = payload.get("instruments")
    if not isinstance(raw, list):
        raise ValueError("paper universe instruments are malformed")
    contracts: dict[str, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("paper universe instrument is malformed")
        identifier = str(item.get("instrument_identifier") or "").strip()
        if not identifier or identifier in contracts:
            raise ValueError("paper universe instrument identities are invalid")
        contracts[identifier] = dict(item)
    return contracts


def _current_evidence_contracts(evaluated_at: datetime) -> dict[str, dict[str, object]] | None:
    """Load current signed evidence scope without provider acquisition or refresh."""

    values = os.environ
    try:
        point = ensure_point_in_time_snapshot(
            cutoff=evaluated_at,
            values=values,
            allow_refresh=False,
        )
        scope = load_evidence_state_scope(
            as_of=point.plane_as_of,
            values=values,
        )
        universe, _holding_only = build_evidence_collection_universe(
            evidence_as_of=point.plane_as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            values=values,
        )
        return _instrument_contracts(universe)
    except (ContinuousEvidencePlaneError, OSError, TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class CapabilityScopedDiscoveryResult:
    """Provider-free view of exact instruments whose authority and evidence are current."""

    as_of: datetime
    instruments: tuple[object, ...]
    source_publication_identifier: str | None
    limitations: tuple[str, ...]
    policy_version: str = "capability-scoped-operating-discovery.v3"
    scope_state: str = "capability_scoped"

    @property
    def identifier(self) -> str:
        stamp = self.as_of.strftime("%Y%m%dT%H%M%S%fZ")
        source = self.source_publication_identifier or "bootstrap-only"
        return f"capability-scoped-discovery:{stamp}:{source}"

    @property
    def manifest_fingerprint(self) -> str:
        return self.source_publication_identifier or "no-prior-active-publication"

    @property
    def lanes(self) -> tuple[()]:
        return ()

    def instruments_for_holdings(self, _held_symbols: Iterable[str]) -> tuple[object, ...]:
        return self.instruments


def discover_currently_certified_capabilities(
    *,
    as_of: datetime,
    held_symbols: tuple[str, ...] = (),
    tracked_symbols: tuple[str, ...] = (),
    excluded_symbols: tuple[str, ...] = (),
) -> CapabilityScopedDiscoveryResult:
    """Return prior publication members with both current authority and current evidence.

    ``held_symbols`` and ``tracked_symbols`` are intentionally non-authoritative here.
    Existing holdings retain their separate evidence/exit-continuity path; tracked names
    cannot gain ownership authority merely by being tracked. ``excluded_symbols`` keeps
    the fresh bootstrap/U.S.-discovery set from being duplicated.
    """

    del held_symbols, tracked_symbols
    evaluated_at = _aware(as_of)
    source, publication_identifier = _current_publication_source()
    exclusions = {
        str(item).strip().upper()
        for item in excluded_symbols
        if str(item).strip()
    }

    if source is None or publication_identifier is None:
        return CapabilityScopedDiscoveryResult(
            as_of=evaluated_at,
            instruments=(),
            source_publication_identifier=None,
            limitations=(
                "No prior active paper-universe publication is available yet; the operating CIO proceeds with freshly qualified bootstrap and U.S.-discovery instruments only.",
                "Comprehensive all-market discovery remains an independent coverage process and is not an operating ignition gate.",
            ),
        )

    try:
        qualified = load_active_paper_universe_for_publication(
            publication_identifier,
            path=source,
            evaluated_at=evaluated_at,
        )
        qualified_contracts = _instrument_contracts(qualified)
    except (OSError, TypeError, ValueError) as error:
        return CapabilityScopedDiscoveryResult(
            as_of=evaluated_at,
            instruments=(),
            source_publication_identifier=publication_identifier,
            limitations=(
                "The prior active publication could not supply a currently certified carry-forward set; no dynamic instrument receives authority from stale or invalid state.",
                f"Capability carry-forward unavailable: {type(error).__name__}",
                "Comprehensive all-market discovery remains independent from the operating CIO path.",
            ),
        )

    evidence_contracts = _current_evidence_contracts(evaluated_at)
    if evidence_contracts is None:
        return CapabilityScopedDiscoveryResult(
            as_of=evaluated_at,
            instruments=(),
            source_publication_identifier=publication_identifier,
            limitations=(
                "Current signed global evidence is unavailable; dynamic global carry-forward is withheld for this CIO cycle without blocking independently qualified bootstrap or U.S.-discovery instruments.",
                "No stale or structurally changed instrument receives paper-allocation authority.",
            ),
        )

    instruments = tuple(
        item
        for item in qualified.instruments
        if str(getattr(item, "symbol", "")).strip().upper() not in exclusions
        and evidence_contracts.get(str(getattr(item, "instrument_identifier", "")).strip())
        == qualified_contracts.get(str(getattr(item, "instrument_identifier", "")).strip())
    )
    withheld = len(qualified.instruments) - len(instruments)
    return CapabilityScopedDiscoveryResult(
        as_of=evaluated_at,
        instruments=instruments,
        source_publication_identifier=publication_identifier,
        limitations=(
            "Operational global scope is the intersection of the latest published universe, exact current capability authority, and exact current signed evidence coverage.",
            "Missing, expired, or evidence-uncovered market capabilities block only the affected instruments; they do not block independently qualified instruments or the canonical portfolio loop.",
            f"{withheld} active-publication instruments were outside this carry-forward set because they were already supplied by fresh discovery or lacked exact current evidence.",
            "All-market discovery/certification continues separately and may expand future operating publications.",
        ),
    )


__all__ = [
    "CapabilityScopedDiscoveryResult",
    "discover_currently_certified_capabilities",
]
