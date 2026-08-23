"""Remove the duplicate full evidence graph from production portfolio marking.

Production context needs current marks before it can compute exact portfolio weights, but
those marks come from the same point-in-time market feature function used by the final
paper-evidence build. Building the complete candidate/specialist graph once merely to read
holding prices creates a large avoidable memory peak.

This module replaces only that orchestration seam on Render. Canonical held-position marks
are computed through ``production_paper_evidence._features`` with the same timestamp,
quote-age, provider-clock, scheduled-market, and mandatory-holding rules. The complete
governed paper-evidence graph is then built exactly once against the marked portfolio and
must reproduce the preliminary marks exactly. Any mismatch fails closed.

No market membership, evidence threshold, specialist/CIO authority, construction,
execution, memory boundary, or paper-only rule is changed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import SimpleNamespace

import production_context_publication_governed as _governed
import production_paper_evidence as _evidence


_INSTALLED_ATTR = "_single_pass_marked_paper_evidence_installed"


def build_holding_marks(
    *,
    universe,
    decision_as_of: datetime,
    cash_expected_return: float,
    portfolio,
    payload: Mapping[str, object],
) -> tuple[tuple[str, float], ...]:
    """Build only mandatory held-position marks through the canonical feature path."""

    as_of = _evidence._aware(decision_as_of, field_name="decision_as_of")
    if portfolio.as_of != as_of:
        raise _evidence.ProductionPaperEvidenceError(
            "portfolio and paper evidence must share the exact decision timestamp"
        )

    bars = payload.get("bars")
    quotes = payload.get("quotes")
    if not isinstance(bars, Mapping) or not isinstance(quotes, Mapping):
        raise _evidence.ProductionPaperEvidenceError("bars and quotes must be mappings")

    raw_scheduled_closed_symbols = payload.get("_scheduled_closed_symbols", ())
    if not isinstance(raw_scheduled_closed_symbols, Sequence) or isinstance(
        raw_scheduled_closed_symbols,
        (str, bytes),
    ):
        raise _evidence.ProductionPaperEvidenceError(
            "scheduled-closed symbol detail must be a sequence"
        )
    scheduled_closed_symbols = frozenset(
        str(symbol).strip().upper()
        for symbol in raw_scheduled_closed_symbols
        if str(symbol).strip()
    )

    instrument_by_symbol = {item.symbol: item for item in universe.instruments}
    unknown_scheduled_closed = sorted(
        scheduled_closed_symbols - set(instrument_by_symbol)
    )
    if unknown_scheduled_closed:
        raise _evidence.ProductionPaperEvidenceError(
            "scheduled-closed symbols are outside the governed paper universe: "
            f"{unknown_scheduled_closed}"
        )

    canonical_holding_symbols = {item.symbol for item in portfolio.positions}
    unknown_holdings = sorted(canonical_holding_symbols - set(instrument_by_symbol))
    if unknown_holdings:
        raise _evidence.ProductionPaperEvidenceError(
            f"canonical holdings are outside the governed paper universe: {unknown_holdings}"
        )
    closed_holdings = sorted(canonical_holding_symbols & scheduled_closed_symbols)
    if closed_holdings:
        raise _evidence.ProductionPaperEvidenceError(
            "mandatory holding evidence is unavailable while the instrument's market is "
            f"scheduled closed: {closed_holdings[0]}"
        )
    if portfolio.nav <= 0.0:
        raise _evidence.ProductionPaperEvidenceError(
            "canonical portfolio NAV must be positive"
        )

    live_collection = payload.get("_live_collection") is True
    maximum_future_skew_seconds = -1 if live_collection else 0
    future_reference_at = as_of
    if live_collection:
        raw_provider_clock = payload.get("provider_clock")
        if not isinstance(raw_provider_clock, Mapping):
            raise _evidence.ProductionPaperEvidenceError(
                "live paper evidence payload is missing the Alpaca market clock"
            )
        future_reference_at = _evidence._timestamp(
            raw_provider_clock.get("timestamp"),
            field_name="Alpaca market clock timestamp",
        )
        if abs((future_reference_at - as_of).total_seconds()) > 900:
            raise _evidence.ProductionPaperEvidenceError(
                "Alpaca market clock differs from the collection-complete decision timestamp by more than 15 minutes"
            )

    marks: list[tuple[str, float]] = []
    for position in portfolio.positions:
        try:
            features = _evidence._features(
                position.symbol,
                bars.get(position.symbol),
                quotes.get(position.symbol),
                as_of=as_of,
                cash_expected_return=cash_expected_return,
                maximum_quote_age_minutes=universe.maximum_quote_age_minutes,
                maximum_future_skew_seconds=maximum_future_skew_seconds,
                future_reference_at=future_reference_at,
            )
        except (
            _evidence.ProductionPaperEvidenceError,
            TypeError,
            ValueError,
        ) as error:
            raise _evidence.ProductionPaperEvidenceError(
                f"mandatory holding evidence failed for {position.symbol}: {error}"
            ) from error
        marks.append((position.symbol, float(features.current_price)))
    return tuple(marks)


def _single_pass_build_marked_paper_evidence(
    *,
    universe,
    decision_as_of: datetime,
    cash_expected_return: float,
    tentative,
    evidence_payload: Mapping[str, object],
    progress_probe,
):
    """Mark holdings cheaply, then construct one complete governed evidence graph."""

    if not tentative.positions:
        return _ORIGINAL_BUILD_MARKED_PAPER_EVIDENCE(
            universe=universe,
            decision_as_of=decision_as_of,
            cash_expected_return=cash_expected_return,
            tentative=tentative,
            evidence_payload=evidence_payload,
            progress_probe=progress_probe,
        )

    holding_marks = build_holding_marks(
        universe=universe,
        decision_as_of=decision_as_of,
        cash_expected_return=cash_expected_return,
        portfolio=tentative,
        payload=evidence_payload,
    )
    if progress_probe is not None:
        # Preserve the established stage name for telemetry consumers while replacing
        # its old full candidate graph with the lightweight mandatory-mark pass.
        progress_probe("production_context_preliminary_evidence_built")

    marked = _governed._mark_portfolio(
        tentative,
        SimpleNamespace(candidates=(), holding_marks=holding_marks),
        decision_as_of=decision_as_of,
    )
    if progress_probe is not None:
        progress_probe("production_context_portfolio_marked")

    result = _governed.build_paper_evidence(
        universe=universe,
        decision_as_of=decision_as_of,
        cash_expected_return=cash_expected_return,
        portfolio=marked,
        payload=evidence_payload,
    )

    final_holding_marks = tuple(getattr(result, "holding_marks", ()))
    if final_holding_marks != holding_marks:
        raise _evidence.ProductionPaperEvidenceError(
            "final governed evidence holding marks differ from the preliminary canonical marks"
        )
    # Retain the pre-existing candidate-vs-holding mark consistency check as part of the
    # final fail-closed validation. The returned snapshot must remain exactly the one used
    # to calculate final portfolio weights.
    reconciled = _governed._mark_portfolio(
        marked,
        result,
        decision_as_of=decision_as_of,
    )
    if reconciled != marked:
        raise _evidence.ProductionPaperEvidenceError(
            "final governed evidence changed canonical portfolio marks after construction"
        )

    if progress_probe is not None:
        progress_probe("production_context_evidence_built")
    return marked, result


_ORIGINAL_BUILD_MARKED_PAPER_EVIDENCE = _governed._build_marked_paper_evidence


def install() -> None:
    """Install the single-pass production-context evidence seam exactly once."""

    if getattr(_governed, _INSTALLED_ATTR, False):
        return
    _single_pass_build_marked_paper_evidence._single_pass_marked_paper_evidence = True  # type: ignore[attr-defined]
    _governed._build_marked_paper_evidence = _single_pass_build_marked_paper_evidence
    setattr(_governed, _INSTALLED_ATTR, True)


__all__ = ["build_holding_marks", "install"]
