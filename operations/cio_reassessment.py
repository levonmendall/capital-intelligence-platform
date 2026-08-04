"""Governed multi-cycle CIO reassessment interfaces."""

from __future__ import annotations

from datetime import timedelta

from api.config import ApiSettings
from operations.cio_after_close import (
    AfterCloseLearningResult,
    AfterCloseOpportunityReviewer,
)
from operations.cio_material_reassessment import ReassessmentResult
from operations.investor_material_reassessment import (
    InvestorMaterialCIOReassessmentEngine,
)


MaterialCIOReassessmentEngine = InvestorMaterialCIOReassessmentEngine


def build_default_reassessment_engine(
    settings: ApiSettings,
) -> MaterialCIOReassessmentEngine:
    root = settings.portfolio_database.parent
    return MaterialCIOReassessmentEngine(
        state_path=root / "cio-material-reassessment-state.json",
        timezone_name=settings.scheduler_timezone,
        schedule_times=settings.scheduler_times,
        scan_interval=timedelta(seconds=settings.scheduler_scan_seconds),
        event_cooldown=timedelta(
            minutes=settings.scheduler_event_cooldown_minutes
        ),
        benchmark_move_threshold=settings.scheduler_benchmark_move_threshold,
        instrument_move_threshold=settings.scheduler_instrument_move_threshold,
        company_move_threshold=settings.scheduler_company_move_threshold,
        active_universe_path=root / "active-paper-universe.json",
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
