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
        result = SQLiteAnalyticalEngineStore(path, read_only=True).latest(
            "global_liquidity",
            at_or_before=as_of,
        )
    except (OSError, ValueError, sqlite3.Error):
        return ()
    return () if result is None else (result,)


def _attach_analytical_context(
    brief: PersonalCIOBrief,
    results: tuple[AnalyticalEngineResult, ...],
) -> PersonalCIOBrief:
    liquidity = next(
        (item for item in results if item.engine == "global_liquidity"),
        None,
    )
    if liquidity is None:
        return brief

    evidence = list(brief.evidence_identifiers)
    evidence.append(liquidity.identifier)
    evidence.extend(item.identifier for item in liquidity.evidence)
    conditions = list(brief.review_conditions)
    conditions.extend(liquidity.review_conditions)

    if liquidity.data_status is EngineDataStatus.UNAVAILABLE:
        conditions.append(
            "Global liquidity evidence is unavailable and should not influence action."
        )
        return replace(
            brief,
            review_conditions=tuple(dict.fromkeys(conditions)),
            evidence_identifiers=tuple(dict.fromkeys(evidence)),
        )

    liquidity_context = (
        f" Global liquidity: {liquidity.summary} {liquidity.explanation}"
    )
    transmission = (
        ""
        if not liquidity.transmission_channels
        else " Liquidity transmission: " + liquidity.transmission_channels[0]
    )
    if liquidity.data_status is EngineDataStatus.STALE:
        conditions.append(
            "Refresh global liquidity evidence before relying on its direction."
        )
    elif liquidity.data_status is EngineDataStatus.INCOMPLETE:
        conditions.append(
            "Treat the global liquidity conclusion cautiously because coverage is incomplete."
        )
    return replace(
        brief,
        why_it_matters=(brief.why_it_matters + liquidity_context).strip(),
        portfolio_effect=(brief.portfolio_effect + transmission).strip(),
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
        else tuple(item for item in analytical_results if item.as_of <= brief.as_of)
    )
    return _attach_analytical_context(brief, results)


__all__ = ["build_personal_cio_brief"]
