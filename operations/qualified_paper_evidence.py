"""Provider-free production probes for immutable paper evidence snapshots.

Capability-scoped production consumes the independent operating evidence plane rather than
the comprehensive discovery generation.  Full-discovery mode retains the legacy qualified
plane.  In either mode the source snapshot is verified against the exact universe that the
evidence owner signed before a CIO subset can be projected from it.

Projection never creates evidence, never refreshes providers, and cannot add an instrument
that was absent from the signed source universe.
"""

from __future__ import annotations

import os
from collections.abc import Mapping as MappingABC
from datetime import datetime, timezone
from typing import Iterator, Mapping

from operations.capability_operating_evidence import (
    CapabilityOperatingEvidenceError,
    load_capability_operating_evidence,
)
from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
)
from operations.evidence_collection_universe import build_evidence_collection_universe
from operations.evidence_state_scope import load_evidence_state_scope
from operations.free_paper_pilot import free_paper_pilot_universe_payload
from operations.paper_evidence_snapshot import (
    PaperEvidenceSnapshotError,
    load_paper_evidence_snapshot,
    universe_signature,
)

_SNAPSHOT_ENV = "CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"
_PROJECTION_ENV = "CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_PROJECTION_SIGNATURE"


class _SubsetMapping(MappingABC[str, object]):
    """Lazy, read-only mapping view restricted to an allowed key set."""

    def __init__(self, source: Mapping[str, object], allowed: set[str]) -> None:
        self._source = source
        self._allowed = frozenset(allowed)

    def __getitem__(self, key: str) -> object:
        if key not in self._allowed:
            raise KeyError(key)
        return self._source[key]

    def __iter__(self) -> Iterator[str]:
        for key in self._source:
            if key in self._allowed:
                yield key

    def __len__(self) -> int:
        return sum(1 for key in self._source if key in self._allowed)


def _enabled(raw: object) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _capability_scoped_operation_enabled(values: Mapping[str, str]) -> bool:
    explicit = values.get("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION")
    if explicit is not None and str(explicit).strip():
        return _enabled(explicit)
    return _enabled(values.get("RENDER"))


def production_snapshot_probe_enabled(values=None) -> bool:
    resolved = os.environ if values is None else values
    production = (
        str(resolved.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "")).strip().lower()
        == "production"
        or _enabled(resolved.get("RENDER"))
    )
    if not production:
        return False
    if _capability_scoped_operation_enabled(resolved):
        return True
    return evidence_plane_enabled(resolved)


def _qualified_snapshot_and_universe_for_cutoff(cutoff: datetime):
    """Load the active evidence owner's exact immutable snapshot and signed universe."""

    values = os.environ
    if not production_snapshot_probe_enabled(values):
        raise RuntimeError("qualified paper evidence probe is production-only")

    if _capability_scoped_operation_enabled(values):
        try:
            operating = load_capability_operating_evidence(
                cutoff=cutoff,
                values=values,
            )
        except CapabilityOperatingEvidenceError as error:
            raise RuntimeError(
                f"capability operating evidence snapshot is not ready: {error}"
            ) from error
        values[_SNAPSHOT_ENV] = operating.snapshot_id
        return operating.snapshot, operating.universe

    try:
        point_snapshot = ensure_point_in_time_snapshot(
            cutoff=cutoff,
            values=values,
            allow_refresh=False,
        )
        scope = load_evidence_state_scope(
            as_of=point_snapshot.plane_as_of,
            values=values,
        )
        universe, _holding_only = build_evidence_collection_universe(
            evidence_as_of=point_snapshot.plane_as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            values=values,
        )
        snapshot = load_paper_evidence_snapshot(
            evidence_as_of=point_snapshot.plane_as_of,
            universe=universe,
            values=values,
        )
    except (ContinuousEvidencePlaneError, PaperEvidenceSnapshotError) as error:
        raise RuntimeError(
            f"qualified paper evidence snapshot is not ready: {error}"
        ) from error
    values[_SNAPSHOT_ENV] = snapshot.snapshot_id
    return snapshot, universe


def _qualified_snapshot_for_cutoff(cutoff: datetime):
    snapshot, _universe = _qualified_snapshot_and_universe_for_cutoff(cutoff)
    return snapshot


def _universe_contract(universe) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return evidence-relevant universe settings and exact instrument contracts."""

    try:
        payload = free_paper_pilot_universe_payload(universe)
    except (TypeError, ValueError, AttributeError) as error:
        raise RuntimeError("qualified paper evidence universe is malformed") from error

    contract = {
        "schema_version": payload.get("schema_version"),
        "portfolio_code": payload.get("portfolio_code"),
        "reporting_currency": payload.get("reporting_currency"),
        "quote_provider": payload.get("quote_provider"),
        "maximum_quote_age_minutes": payload.get("maximum_quote_age_minutes"),
    }
    raw_instruments = payload.get("instruments")
    if not isinstance(raw_instruments, list):
        raise RuntimeError("qualified paper evidence instruments are malformed")

    instruments: dict[str, dict[str, object]] = {}
    for raw in raw_instruments:
        if not isinstance(raw, MappingABC):
            raise RuntimeError("qualified paper evidence instrument is malformed")
        identifier = str(raw.get("instrument_identifier") or "").strip()
        if not identifier or identifier in instruments:
            raise RuntimeError(
                "qualified paper evidence instrument identities are missing or duplicated"
            )
        instruments[identifier] = dict(raw)
    return contract, instruments


def _validate_exact_evidence_subset(*, requested_universe, source_universe) -> set[str]:
    """Prove the CIO universe is an exact structural subset of signed evidence scope."""

    requested_contract, requested = _universe_contract(requested_universe)
    source_contract, source = _universe_contract(source_universe)
    if requested_contract != source_contract:
        raise RuntimeError("qualified paper evidence universe contract changed")
    if not requested:
        raise RuntimeError("qualified paper evidence projection cannot be empty")

    missing: list[str] = []
    changed: list[str] = []
    symbols: set[str] = set()
    for identifier, contract in requested.items():
        source_contract_for_instrument = source.get(identifier)
        if source_contract_for_instrument is None:
            missing.append(identifier)
            continue
        if source_contract_for_instrument != contract:
            changed.append(identifier)
            continue
        symbol = str(contract.get("symbol") or "").strip().upper()
        if not symbol:
            changed.append(identifier)
            continue
        symbols.add(symbol)

    if missing:
        raise RuntimeError(
            "qualified paper evidence projection requested instruments absent from the "
            "signed snapshot: " + ", ".join(sorted(missing)[:20])
        )
    if changed:
        raise RuntimeError(
            "qualified paper evidence projection detected changed instrument contracts: "
            + ", ".join(sorted(changed)[:20])
        )
    return symbols


def _project_payload(*, snapshot, requested_universe, source_universe) -> Mapping[str, object]:
    """Return a lazy evidence view containing only exact requested instrument symbols."""

    symbols = _validate_exact_evidence_subset(
        requested_universe=requested_universe,
        source_universe=source_universe,
    )
    payload = dict(snapshot.payload)
    for key in ("bars", "quotes", "company_facts", "_direct_market_errors"):
        value = payload.get(key)
        if isinstance(value, MappingABC):
            payload[key] = _SubsetMapping(value, symbols)

    closed = payload.get("_scheduled_closed_symbols")
    if isinstance(closed, (tuple, list)):
        payload["_scheduled_closed_symbols"] = tuple(
            str(symbol)
            for symbol in closed
            if str(symbol).strip().upper() in symbols
        )

    requested_signature = universe_signature(requested_universe)
    payload["_paper_evidence_projection"] = {
        "source_snapshot_id": snapshot.snapshot_id,
        "source_universe_signature": universe_signature(source_universe),
        "requested_universe_signature": requested_signature,
        "source_instrument_count": len(tuple(source_universe.instruments)),
        "requested_instrument_count": len(tuple(requested_universe.instruments)),
        "exact_structural_subset": True,
        "provider_refresh_permitted": False,
        "investment_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    os.environ[_PROJECTION_ENV] = requested_signature
    return payload


def qualified_paper_readiness_probe(universe, *, cutoff: datetime | None = None):
    """Read broker/account/asset readiness acquired by the evidence owner."""

    snapshot = _qualified_snapshot_for_cutoff(cutoff or datetime.now(timezone.utc))
    provider_clock = snapshot.payload.get("provider_clock")
    if not isinstance(provider_clock, Mapping):
        raise RuntimeError("qualified paper readiness metadata is unavailable")
    readiness = provider_clock.get("paper_readiness")
    if not isinstance(readiness, Mapping):
        raise RuntimeError("qualified paper readiness metadata is unavailable")
    if str(readiness.get("universe_identifier") or "") != str(universe.identifier):
        raise RuntimeError("qualified paper readiness universe changed")
    return dict(readiness)


def qualified_cash_probe(*, cutoff: datetime | None = None):
    """Read the qualified DGS10 cash-return observation without FRED acquisition."""

    snapshot = _qualified_snapshot_for_cutoff(cutoff or datetime.now(timezone.utc))
    macro = snapshot.payload.get("macro")
    if not isinstance(macro, Mapping) or "DGS10" not in macro:
        raise RuntimeError("qualified DGS10 cash-return evidence is unavailable")
    return macro["DGS10"]


def qualified_paper_evidence_probe(universe, decision_as_of):
    """Project the signed evidence snapshot onto the capability-authorized CIO subset."""

    snapshot, source_universe = _qualified_snapshot_and_universe_for_cutoff(decision_as_of)
    return _project_payload(
        snapshot=snapshot,
        requested_universe=universe,
        source_universe=source_universe,
    )


__all__ = [
    "production_snapshot_probe_enabled",
    "qualified_cash_probe",
    "qualified_paper_evidence_probe",
    "qualified_paper_readiness_probe",
]
