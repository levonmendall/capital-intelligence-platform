"""Operational discovery boundary for the capability-scoped CIO runtime.

The all-market discovery/certification plane remains responsible for expanding global
coverage.  The canonical CIO operating path must not wait for every market family to
re-certify simultaneously.  This adapter therefore carries forward only instruments
from the most recent active publication that still have exact paper-allocation
authority at the current timestamp.

It performs no provider discovery, creates no certification, and has no investment or
execution authority.  New instruments can enter only after another governed process
has discovered, qualified, and certified them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from operations.active_paper_universe import load_active_paper_universe_for_publication
from operations.free_paper_pilot import active_paper_universe_path


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


@dataclass(frozen=True, slots=True)
class CapabilityScopedDiscoveryResult:
    """Provider-free view of exact instruments whose authority is still current."""

    as_of: datetime
    instruments: tuple[object, ...]
    source_publication_identifier: str | None
    limitations: tuple[str, ...]
    policy_version: str = "capability-scoped-operating-discovery.v2"
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
    """Return only prior publication members whose exact authority remains active.

    ``held_symbols`` and ``tracked_symbols`` are intentionally non-authoritative here.
    Existing holdings retain their separate evidence/exit-continuity path; tracked names
    cannot gain ownership authority merely by being tracked.  ``excluded_symbols`` keeps
    the fresh bootstrap/U.S.-discovery set from being duplicated.
    """

    del held_symbols, tracked_symbols
    evaluated_at = _aware(as_of)
    source = active_paper_universe_path()
    publication_identifier = _publication_identifier(source)
    exclusions = {str(item).strip().upper() for item in excluded_symbols if str(item).strip()}

    if publication_identifier is None:
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

    instruments = tuple(
        item
        for item in qualified.instruments
        if str(getattr(item, "symbol", "")).strip().upper() not in exclusions
    )
    return CapabilityScopedDiscoveryResult(
        as_of=evaluated_at,
        instruments=instruments,
        source_publication_identifier=publication_identifier,
        limitations=(
            "Operational global scope is the intersection of the latest published universe and exact capability authority that is still active at this timestamp.",
            "Missing or expired market capabilities block only the affected instruments; they do not block independently qualified instruments or the canonical portfolio loop.",
            "All-market discovery/certification continues separately and may expand future operating publications.",
        ),
    )


__all__ = [
    "CapabilityScopedDiscoveryResult",
    "discover_currently_certified_capabilities",
]
