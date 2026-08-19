"""Provider-free candidate views for the capability-scoped CIO runtime.

Comprehensive discovery is an asynchronous coverage expander. Production candidate
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

from cio import CandidateAssetClass
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
    """Provider-free view of exact instruments whose authority and evidence are current.

    The governed production-context publisher historically consumed broad-discovery
    metadata (`screened_asset_count`, `snapshot_covered_count`, and `selected`) in addition
    to the discovered instrument contracts. Capability-scoped discovery supplies the same
    truthful publication metadata without pretending that asynchronous comprehensive
    discovery ran: ``screened_asset_count`` counts current authorized instruments that
    survive the view filters, while ``snapshot_covered_count``/``selected`` count the exact
    subset also present in the fresh operating-evidence snapshot.
    """

    as_of: datetime
    instruments: tuple[object, ...]
    source_publication_identifier: str | None
    limitations: tuple[str, ...]
    observed_prices: tuple[tuple[str, float, str], ...] = ()
    screened_asset_count: int = 0
    snapshot_covered_count: int = 0
    policy_version: str = "capability-scoped-operating-discovery.v6-publication-metadata"
    scope_state: str = "capability_scoped"

    def __post_init__(self) -> None:
        if self.screened_asset_count < 0 or self.snapshot_covered_count < 0:
            raise ValueError("capability discovery counts cannot be negative")
        if self.snapshot_covered_count != len(self.instruments):
            raise ValueError(
                "snapshot_covered_count must equal the exact selected instrument count"
            )
        if self.snapshot_covered_count > self.screened_asset_count:
            raise ValueError(
                "snapshot-covered instruments cannot exceed screened authorized instruments"
            )

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

    @property
    def selected(self) -> tuple[object, ...]:
        """Legacy publication-compatible name for the exact operable selection."""

        return self.instruments

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

    authorized_contracts = _instrument_contracts(authorized)
    screened = tuple(
        item
        for item in authorized.instruments
        if str(getattr(item, "symbol", "")).strip().upper() not in exclusions
        and (
            not us_equities_only
            or getattr(item, "execution_asset_class", None)
            is CandidateAssetClass.US_EQUITY
        )
    )
    evidence_contracts = _current_evidence_contracts(evaluated_at)
    if evidence_contracts is None:
        return CapabilityScopedDiscoveryResult(
            as_of=evaluated_at,
            instruments=(),
            source_publication_identifier=publication_identifier,
            limitations=(
                "Fresh capability operating evidence is unavailable; dynamic candidates are withheld for this CIO cycle without changing their certification state.",
                "No stale or structurally changed instrument receives paper-allocation authority.",
            ),
            screened_asset_count=len(screened),
            snapshot_covered_count=0,
        )

    selected = tuple(
        item
        for item in screened
        if evidence_contracts.get(
            str(getattr(item, "instrument_identifier", "")).strip()
        )
        == authorized_contracts.get(
            str(getattr(item, "instrument_identifier", "")).strip()
        )
    )

    return CapabilityScopedDiscoveryResult(
        as_of=evaluated_at,
        instruments=selected,
        source_publication_identifier=publication_identifier,
        limitations=(
            "Candidate membership requires exact current instrument capability authority and exact membership in the fresh independent operating-evidence snapshot.",
            "Comprehensive all-market discovery can expand future active publications but cannot block this current operating set.",
        ),
        screened_asset_count=len(screened),
        snapshot_covered_count=len(selected),
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
