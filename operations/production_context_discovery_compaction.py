"""Bound production-context discovery and portfolio-state handoffs before final evidence.

Production context needs discovery to establish the governed instrument universe, but after
that handoff it consumes only a small set of discovery metadata plus observed prices used
for opportunity-outcome reconciliation. The canonical discovery results additionally
retain detailed selected/excluded evidence graphs which are no longer authoritative once
the instrument contracts have been materialized into the governed universe.

The final portfolio handoff also needs canonical append-only integrity plus, at most, the
snapshot at the exact decision timestamp. Rehydrating thousands of historical snapshots
while final evidence is resident creates a transient anonymous-memory peak without adding
decision authority. This Render-only installation seam therefore streams the unchanged
hash-chain validation and performs a bounded exact-timestamp lookup before falling back to
the single latest canonical snapshot.

These lifecycle changes do not alter discovery membership, rankings, evidence requirements,
point-in-time lineage, market scope, memory limits, CIO authority, construction, execution,
or the paper-only boundary.
"""

from __future__ import annotations

import gc
import json
from dataclasses import dataclass, replace
from datetime import timezone
from typing import Any

import production_context_publication_governed as _governed
from portfolio.state import (
    CanonicalPortfolioCompatibilityError,
    CanonicalPortfolioIntegrityError,
    snapshot_from_dict,
)


_INSTALLED_ATTR = "_production_context_discovery_compaction_installed"
_ORIGINAL_DISCOVER_US_EQUITIES = _governed.discover_us_equities
_ORIGINAL_DISCOVER_COMPREHENSIVE_SCOPE = _governed._discover_comprehensive_scope
_ORIGINAL_TENTATIVE_PORTFOLIO = _governed._tentative_portfolio


@dataclass(frozen=True, slots=True)
class _CompactEquityDiscovery:
    identifier: str
    as_of: object
    policy_version: str
    screened_asset_count: int
    snapshot_covered_count: int
    deep_shortlist_count: int
    selected_count: int
    observed_prices: tuple[object, ...]
    security_master_snapshot_identifier: str
    instruments: tuple[object, ...]

    @property
    def selected(self) -> range:
        """Expose only the selected cardinality required by context telemetry."""

        return range(self.selected_count)

    def instruments_for_holdings(self, _held_symbols) -> tuple[object, ...]:
        """Return the exact contracts already materialized for this holding set."""

        return self.instruments


@dataclass(frozen=True, slots=True)
class _CompactLane:
    asset_class: object
    catalog_count: int
    deep_analyzed_count: int
    scheduled: bool
    schedule_reason: str
    selected_count: int

    @property
    def selected(self) -> range:
        return range(self.selected_count)


@dataclass(frozen=True, slots=True)
class _CompactComprehensiveDiscovery:
    identifier: str
    manifest_fingerprint: str
    policy_version: str
    scope_state: str
    limitations: tuple[str, ...]
    lanes: tuple[_CompactLane, ...]
    instruments: tuple[object, ...]

    def instruments_for_holdings(self, _held_symbols) -> tuple[object, ...]:
        """Return the exact contracts already materialized for this holding set."""

        return self.instruments


def _compact_equity_result(result: Any, *, held_symbols) -> _CompactEquityDiscovery:
    """Retain only production-context consumers of a completed equity discovery."""

    instruments = tuple(result.instruments_for_holdings(held_symbols))
    return _CompactEquityDiscovery(
        identifier=str(result.identifier),
        as_of=getattr(result, "as_of", None),
        policy_version=str(result.policy_version),
        screened_asset_count=int(result.screened_asset_count),
        snapshot_covered_count=int(result.snapshot_covered_count),
        deep_shortlist_count=int(getattr(result, "deep_shortlist_count", 0)),
        selected_count=len(result.selected),
        observed_prices=tuple(result.observed_prices),
        security_master_snapshot_identifier=str(
            result.security_master_snapshot_identifier
        ),
        instruments=instruments,
    )


def _compact_comprehensive_result(
    result: Any,
    *,
    held_symbols,
) -> _CompactComprehensiveDiscovery:
    """Retain terminal accounting metadata without retaining discovery evidence graphs."""

    instruments = tuple(result.instruments_for_holdings(held_symbols))
    lanes = tuple(
        _CompactLane(
            asset_class=lane.asset_class,
            catalog_count=int(lane.catalog_count),
            deep_analyzed_count=int(lane.deep_analyzed_count),
            scheduled=bool(lane.scheduled),
            schedule_reason=str(lane.schedule_reason),
            selected_count=len(lane.selected),
        )
        for lane in result.lanes
    )
    return _CompactComprehensiveDiscovery(
        identifier=str(result.identifier),
        manifest_fingerprint=str(result.manifest_fingerprint),
        policy_version=str(result.policy_version),
        scope_state=str(getattr(result, "scope_state", "complete")),
        limitations=tuple(str(item) for item in getattr(result, "limitations", ())),
        lanes=lanes,
        instruments=instruments,
    )


def _compact_discover_us_equities(*args, **kwargs):
    held_symbols = tuple(kwargs.get("held_symbols", ()))
    result = _ORIGINAL_DISCOVER_US_EQUITIES(*args, **kwargs)
    compact = _compact_equity_result(result, held_symbols=held_symbols)
    del result
    gc.collect()
    return compact


def _compact_discover_comprehensive_scope(
    *,
    as_of,
    held_symbols,
    tracked_symbols,
    excluded_symbols,
    probe,
    required,
):
    result = _ORIGINAL_DISCOVER_COMPREHENSIVE_SCOPE(
        as_of=as_of,
        held_symbols=held_symbols,
        tracked_symbols=tracked_symbols,
        excluded_symbols=excluded_symbols,
        probe=probe,
        required=required,
    )
    compact = _compact_comprehensive_result(result, held_symbols=held_symbols)
    del result
    gc.collect()
    return compact


def _verify_canonical_integrity_streaming(store) -> None:
    """Run the canonical hash-chain verification without retaining the full history."""

    expected_previous = "0" * 64
    with store._connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM {store._TABLE} ORDER BY sequence"
        )
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise CanonicalPortfolioIntegrityError(
                    "portfolio event sequence is not contiguous"
                )
            if str(row["portfolio_code"]).upper() != "COMPOUNDING":
                raise CanonicalPortfolioCompatibilityError(
                    "portfolio history contains a retired or unauthorized portfolio code"
                )
            if str(row["previous_hash"]) != expected_previous:
                raise CanonicalPortfolioIntegrityError(
                    "portfolio event previous-hash link is invalid"
                )
            expected_hash = store._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                portfolio_code=str(row["portfolio_code"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=expected_previous,
            )
            if str(row["content_hash"]) != expected_hash:
                raise CanonicalPortfolioIntegrityError(
                    "portfolio event content hash is invalid"
                )
            expected_previous = expected_hash


def _exact_portfolio_matches(store, *, decision_as_of) -> tuple[object, ...]:
    """Load no more than two snapshots at the decision time for duplicate detection."""

    aware_as_of = _governed._aware(decision_as_of, field_name="decision_as_of")
    occurred_at = aware_as_of.astimezone(timezone.utc).isoformat()
    with store._connect() as connection:
        rows = tuple(
            connection.execute(
                f"SELECT payload_json FROM {store._TABLE} "
                "WHERE portfolio_code = ? AND occurred_at = ? "
                "ORDER BY sequence DESC LIMIT 2",
                ("COMPOUNDING", occurred_at),
            )
        )
    return tuple(
        snapshot_from_dict(json.loads(str(row["payload_json"]))) for row in rows
    )


def _bounded_tentative_portfolio(
    *,
    store,
    decision_as_of,
    context_identifier,
):
    """Preserve governed tentative-portfolio semantics with bounded history memory."""

    _verify_canonical_integrity_streaming(store)
    matches = _exact_portfolio_matches(store, decision_as_of=decision_as_of)
    if len(matches) > 1:
        raise _governed.ProductionPaperEvidenceError(
            "multiple canonical portfolio snapshots exist at the decision timestamp"
        )
    if matches:
        return matches[0], True
    latest = store.latest("COMPOUNDING")
    if latest is None:
        raise _governed.ProductionPaperEvidenceError(
            "canonical portfolio state is unavailable"
        )
    if latest.as_of > decision_as_of:
        raise _governed.ProductionPaperEvidenceError(
            "canonical portfolio state is future-known"
        )
    if latest.currency_balances:
        raise _governed.ProductionPaperEvidenceError(
            "the USD listed-wrapper pilot cannot publish non-base currency balances"
        )
    if latest.cash_amount <= 0.0:
        raise _governed.ProductionPaperEvidenceError(
            "canonical portfolio must retain positive cash"
        )
    return (
        replace(
            latest,
            identifier=(
                "portfolio:compounding:decision:"
                f"{_governed._stamp(decision_as_of)}"
            ),
            as_of=decision_as_of,
            source_identifiers=tuple(
                dict.fromkeys((*latest.source_identifiers, context_identifier))
            ),
        ),
        False,
    )


def install() -> None:
    """Install bounded production-context handoffs exactly once."""

    if getattr(_governed, _INSTALLED_ATTR, False):
        return
    _governed.discover_us_equities = _compact_discover_us_equities
    _governed._discover_comprehensive_scope = _compact_discover_comprehensive_scope
    _governed._tentative_portfolio = _bounded_tentative_portfolio
    setattr(_governed, _INSTALLED_ATTR, True)


__all__ = ["install"]
