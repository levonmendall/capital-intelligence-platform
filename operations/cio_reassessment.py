"""Governed multi-cycle CIO reassessment interfaces."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from api.config import ApiSettings
from operations.cio_after_close import (
    AfterCloseLearningResult,
    AfterCloseOpportunityReviewer,
)
from operations.cio_material_reassessment import ReassessmentResult
from operations.global_opportunity_reassessment import (
    GlobalOpportunityMaterialCIOReassessmentEngine,
)


class MaterialCIOReassessmentEngine(GlobalOpportunityMaterialCIOReassessmentEngine):
    """Backward-compatible public facade for direct/test construction.

    Historical direct callers receive the established five-minute scan and ten-minute
    scheduled guard defaults. The production builder below explicitly overrides both
    so live opportunity detection remains one-minute with no scheduled suppression.
    """

    def __init__(
        self,
        *,
        scan_interval: timedelta = timedelta(minutes=5),
        scheduled_guard: timedelta = timedelta(minutes=10),
        **kwargs: Any,
    ) -> None:
        super().__init__(
            scan_interval=scan_interval,
            scheduled_guard=scheduled_guard,
            **kwargs,
        )


_OPPORTUNITY_SCAN_MAX_INTERVAL = timedelta(minutes=1)


def build_default_reassessment_engine(
    settings: ApiSettings,
) -> MaterialCIOReassessmentEngine:
    root = settings.portfolio_database.parent
    configured_scan = timedelta(seconds=settings.scheduler_scan_seconds)
    return MaterialCIOReassessmentEngine(
        state_path=root / "cio-material-reassessment-state.json",
        timezone_name=settings.scheduler_timezone,
        schedule_times=settings.scheduler_times,
        # Scheduled full-market cycles remain backstops. Opportunity detection is
        # allowed to request the CIO at least once per minute even when an older
        # deployment still carries a slower scheduler scan setting.
        scan_interval=min(configured_scan, _OPPORTUNITY_SCAN_MAX_INTERVAL),
        # The historical setting is retained as a same-opportunity deduplication
        # lifetime. It no longer suppresses a different opportunity.
        event_cooldown=timedelta(
            minutes=settings.scheduler_event_cooldown_minutes
        ),
        # Distinct event-cycle keys already provide collision protection, so there
        # is no reason to suppress a real opportunity merely because a scheduled
        # review is imminent or just completed.
        scheduled_guard=timedelta(0),
        benchmark_move_threshold=settings.scheduler_benchmark_move_threshold,
        instrument_move_threshold=settings.scheduler_instrument_move_threshold,
        company_move_threshold=settings.scheduler_company_move_threshold,
        active_universe_path=root / "active-paper-universe.json",
        active_investor_database=settings.journal_database,
    )


def build_default_after_close_reviewer(
    settings: ApiSettings,
) -> AfterCloseOpportunityReviewer:
    root = settings.portfolio_database.parent
    return AfterCloseOpportunityReviewer(
        state_path=root / "after-close-opportunity-review-state.json",
        outcome_store_path=root / "opportunity_outcomes.db",
        timezone_name=settings.scheduler_timezone,
        review_time=settings.scheduler_after_close_time,
    )


__all__ = [
    "AfterCloseLearningResult",
    "AfterCloseOpportunityReviewer",
    "MaterialCIOReassessmentEngine",
    "ReassessmentResult",
    "build_default_after_close_reviewer",
    "build_default_reassessment_engine",
]
