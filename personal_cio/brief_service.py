"""Product-level action policy for the canonical Personal CIO Brief."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from intelligence.analytical_engine import AnalyticalEngineResult, EngineDataStatus
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from personal_cio.models import (
    ActionStatus,
    InvestmentPolicyProfile,
    InvestorGoal,
    PersonalCIOBrief,
)
from personal_cio.service import build_personal_cio_brief as _build_base_brief


_ENGINE_ORDER = ("global_liquidity", "business_cycle")
_ENGINE_LABELS = {
    "global_liquidity": "Global liquidity",
    "business_cycle": "Business cycle",
}
_ENGINE_TRANSMISSION_LABELS = {
    "global_liquidity": "Liquidity transmission",
    "business_cycle": "Business-cycle transmission",
}


def _default_analytical_database() -> Path:
    explicit = os.environ.get("CAPITAL_INTELLIGENCE_ANALYTICAL_ENGINE_DATABASE")
    if explicit and explicit.strip():
        return Path(explicit).expanduser()
    snapshot = os.environ.get("CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE")
    if snapshot and snapshot.strip():
        return Path(snapshot).expanduser().with_name("analytical_engines.db")
    data_dir = Path(
        os.environ.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return data_dir / "analytical_engines.db"


def _latest_analytical_results(
    as_of: datetime,
    database: Path | None,
) -> tuple[AnalyticalEngineResult, ...]:
    path = database or _default_analytical_database()
    if not path.exists():
        return ()
    try:
        store = SQLiteAnalyticalEngineStore(path, read_only=True)
        results = tuple(
            result
            for engine in _ENGINE_ORDER
            if (
                result := store.latest(
                    engine,
                    at_or_before=as_of,
                )
            )
            is not None
        )
    except (OSError, ValueError, sqlite3.Error):
        return ()
    return results


def _attach_analytical_context(
    brief: PersonalCIOBrief,
    results: tuple[AnalyticalEngineResult, ...],
) -> PersonalCIOBrief:
    by_engine = {item.engine: item for item in results}
    why_parts: list[str] = []
    transmission_parts: list[str] = []
    evidence = list(brief.evidence_identifiers)
    conditions = list(brief.review_conditions)

    for engine in _ENGINE_ORDER:
        result = by_engine.get(engine)
        if result is None:
            continue
        label = _ENGINE_LABELS[engine]
        evidence.append(result.identifier)
        evidence.extend(item.identifier for item in result.evidence)
        conditions.extend(result.review_conditions)

        if result.data_status is EngineDataStatus.UNAVAILABLE:
            conditions.append(
                f"{label} evidence is unavailable and should not influence action."
            )
            continue

        why_parts.append(f"{label}: {result.summary} {result.explanation}")
        if result.transmission_channels:
            transmission_parts.append(
                f"{_ENGINE_TRANSMISSION_LABELS[engine]}: "
                + result.transmission_channels[0]
            )
        if result.data_status is EngineDataStatus.STALE:
            conditions.append(
                f"Refresh {label.lower()} evidence before relying on its direction."
            )
        elif result.data_status is EngineDataStatus.INCOMPLETE:
            conditions.append(
                f"Treat the {label.lower()} conclusion cautiously because coverage is incomplete."
            )

    if not by_engine:
        return brief
    why_suffix = " " + " ".join(why_parts) if why_parts else ""
    portfolio_suffix = (
        " " + " ".join(transmission_parts) if transmission_parts else ""
    )
    return replace(
        brief,
        why_it_matters=(brief.why_it_matters + why_suffix).strip(),
        portfolio_effect=(brief.portfolio_effect + portfolio_suffix).strip(),
        review_conditions=tuple(dict.fromkeys(conditions)),
        evidence_identifiers=tuple(dict.fromkeys(evidence)),
    )


def build_personal_cio_brief(
    investor_identifier: str,
    *,
    daily_snapshot: dict[str, Any],
    profile: InvestmentPolicyProfile | None,
    goals: tuple[InvestorGoal, ...],
    portfolios: tuple[dict[str, Any], ...],
    generated_at: datetime | None = None,
    analytical_results: tuple[AnalyticalEngineResult, ...] | None = None,
    analytical_engine_database: Path | None = None,
) -> PersonalCIOBrief:
    """Permit disciplined no-action and add non-decision engine context."""

    brief = _build_base_brief(
        investor_identifier,
        daily_snapshot=daily_snapshot,
        profile=profile,
        goals=goals,
        portfolios=portfolios,
        generated_at=generated_at,
    )
    if (
        bool(daily_snapshot.get("should_alert"))
        and brief.action_status is ActionStatus.REVIEW
        and brief.portfolio_alignment.score is not None
        and brief.portfolio_alignment.score >= 80
        and not brief.portfolio_alignment.conflicts
    ):
        brief = replace(
            brief,
            action_status=ActionStatus.NO_ACTION,
            recommended_action=(
                "No action is necessary. The material market change was reviewed "
                "against the recorded objectives, and the current portfolio "
                "remains appropriately positioned."
            ),
        )
    results = (
        _latest_analytical_results(brief.as_of, analytical_engine_database)
        if analytical_results is None
        else tuple(
            item for item in analytical_results if item.as_of <= brief.as_of
        )
    )
    return _attach_analytical_context(brief, results)


__all__ = ["build_personal_cio_brief"]
