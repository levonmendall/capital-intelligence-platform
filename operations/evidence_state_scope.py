"""Read-only portfolio/learning scope required by continuous market evidence.

Comprehensive discovery deliberately gives current holdings and unresolved learning
symbols continuity treatment.  The evidence owner may read those identities so it can
prepare the correct provider evidence ahead of a CIO cycle.  This module has no authority
to mutate portfolio, learning, screening, CIO, construction, or execution state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from api.config import ApiSettings
from evaluation.opportunity_outcomes import SQLiteOpportunityOutcomeStore
from portfolio.state import SQLiteCanonicalPortfolioStore


@dataclass(frozen=True, slots=True)
class EvidenceStateScope:
    held_symbols: tuple[str, ...]
    tracked_symbols: tuple[str, ...]
    scope_id: str


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence state-scope cutoff must be timezone-aware")
    return value.astimezone(timezone.utc)


def _symbols(values) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(item).strip().upper()
                for item in values
                if str(item).strip()
            }
        )
    )


def load_evidence_state_scope(
    *,
    as_of: datetime,
    values: Mapping[str, str],
) -> EvidenceStateScope:
    """Read the exact continuity identities the evidence plane must cover."""

    cutoff = _aware(as_of)
    settings = ApiSettings.from_env(values)
    portfolio = SQLiteCanonicalPortfolioStore(settings.portfolio_database).latest()
    held = _symbols(
        () if portfolio is None else (position.symbol for position in portfolio.positions)
    )

    outcome_store = SQLiteOpportunityOutcomeStore(
        settings.portfolio_database.with_name("opportunity_outcomes.db")
    )
    # Preserve the governed publication's existing behavior: an unavailable learning
    # store does not authorize a fabricated symbol; it simply contributes no unresolved
    # learning scope for this evidence generation.
    try:
        tracked = _symbols(outcome_store.unresolved_symbols(as_of=cutoff))
    except (OSError, TypeError, ValueError):
        tracked = ()

    material = {
        "schema_version": "evidence-state-scope.v1",
        "held_symbols": list(held),
        "tracked_symbols": list(tracked),
        "investment_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    scope_id = hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return EvidenceStateScope(
        held_symbols=held,
        tracked_symbols=tracked,
        scope_id=scope_id,
    )


__all__ = ["EvidenceStateScope", "load_evidence_state_scope"]
