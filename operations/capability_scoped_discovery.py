"""Provider-free candidate views for the capability-scoped CIO runtime.

Comprehensive discovery is an asynchronous coverage expander.  Production candidate
membership instead comes from the latest active paper publication, exact current
instrument capability authority, and the independent fresh operating-evidence snapshot.
A missing capability or missing fresh evidence therefore removes only that instrument.

This module performs no provider discovery, creates no certification, and has no
investment or execution authority.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from operations.capability_operating_evidence import (
    CapabilityOperatingEvidenceError,
    load_capability_operating_evidence,
)
from operations.capability_operating_universe import load_current_authorized_universe
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


def _current_publication_identifier() -> str | None:
    for path in _candidate_paths():
        identifier = _publication_identifier(path)
        if identifier is not None:
            return identifier
    return None


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
    """Load the fresh independent operating evidence scope without provider calls."""

    try:
        operating = load_capability_operating_evidence(
            cutoff=evaluated_at,
            values=os.environ,
        )
        return _instrument_contracts(operating.universe)
    except (CapabilityOperatingEvidenceError, OSError, TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class CapabilityScopedDiscoveryResult:
    """Provider-free view of exact instruments whose authority and evidence are current."""

    as_of: datetime
    instruments: tuple[object, ...]
    source_publication_identifier: str | None
    limitations: tuple[str, ...]
    observed_prices: tuple[tuple[str, float, str], ...] = ()
    policy_version: str = "capability-scoped-operating-discovery.v4"
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

    @property
    def security_master_snapshot_identifier(self) -> str:
        return f"capability-operating:{self.source_publication_identifier or 'bootstrap-only'}"

    def instruments_for_holdings(self, _held_symbols: Iterable[str]) -> tuple[object, ...]:
        return self.instruments


def _current_candidates(
    *,
    evaluated_at: datetime,
    excluded_symbols: tuple[str, ...],
    us_equities_only: bool,
) -> CapabilityScopedDiscoveryResult:
    publication_identifier = _current_publication_identifier()
    authorized = load_current_authorized_universe(as_of=evaluated_at)
    evidence_contracts = _current_evidence_contracts(evaluated_at)
    exclusions = {
        str(item).strip().upper()
        for item in excluded_symbols
        if str(item).strip()
    }

    if authorized is None:
        return CapabilityScopedDiscoveryResult(
            as_of=evaluated_at,
            instruments=(),
            source_publication_identifier=publication_identifier,
            limitations=(
                "No current active instrument capability publication is available; no dynamic candidate receives allocation authority.",
                "Bootstrap instruments remain governed separately and comprehensive discovery continues asynchronously.",
            ),
        )
    if evidence_contracts is None:
        return CapabilityScopedDiscoveryResult(
            as_of=evaluated_at,
            instruments=(),
            source_publication_identifier=publication_identifier,
            limitations=(
                "Fresh capability operating evidence is unavailable; dynamic candidates are withheld for this CIO cycle without changing their certification state.",
                "No stale or structurally changed instrument receives paper-allocation authority.",
            ),
        )

    authorized_contracts = _instrument_contracts(authorized)
    selected = []
    for item in authorized.instruments:
        symbol = str(getattr(item, "symbol", "")).strip().upper()
        identifier = str(getattr(item, "instrument_identifier", "")).strip()
        if symbol in exclusions:
            continue
        if evidence_contracts.get(identifier) != authorized_contracts.get(identifier):
            continue
        if us_equities_only and not (
            str(getattr(item, "country_code", "")).strip().upper() == "US"
            and str(getattr(item, "instrument_type", "")).strip().lower() == "equity"
        ):
            continue
        selected.append(item)

    return CapabilityScopedDiscoveryResult(
        as_of=evaluated_at,
        instruments=tuple(selected),
        source_publication_identifier=publication_identifier,
        limitations=(
            "Candidate membership requires exact current instrument capability authority and exact membership in the fresh independent operating-evidence snapshot.",
            "Comprehensive all-market discovery can expand future active publications but cannot block this current operating set.",
        ),
    )


def discover_currently_certified_us_equities(
    *,
    as_of: datetime,
    held_symbols: tuple[str, ...] = (),
    tracked_symbols: tuple[str, ...] = (),
    excluded_symbols: tuple[str, ...] = (),
) -> CapabilityScopedDiscoveryResult:
    """Return current individual U.S.-equity candidates without fresh broad discovery."""

    del held_symbols, tracked_symbols
    return _current_candidates(
        evaluated_at=_aware(as_of),
        excluded_symbols=excluded_symbols,
        us_equities_only=True,
    )


def discover_currently_certified_capabilities(
    *,
    as_of: datetime,
    held_symbols: tuple[str, ...] = (),
    tracked_symbols: tuple[str, ...] = (),
    excluded_symbols: tuple[str, ...] = (),
) -> CapabilityScopedDiscoveryResult:
    """Return all current dynamic candidates with both authority and operating evidence."""

    del held_symbols, tracked_symbols
    return _current_candidates(
        evaluated_at=_aware(as_of),
        excluded_symbols=excluded_symbols,
        us_equities_only=False,
    )


__all__ = [
    "CapabilityScopedDiscoveryResult",
    "discover_currently_certified_capabilities",
    "discover_currently_certified_us_equities",
]
