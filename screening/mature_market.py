"""Mature all-market screening wrappers.

The public screening package exports these wrappers so the active path can admit a
broad classified market universe, quarantine instrument-level data gaps, and route
analytically strong but not-yet-authorized markets to research-only committee and
CIO review. Final investment and implementation authority remains unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from data.security_master import Version1UniverseBuilder as StrictVersion1UniverseBuilder
from screening.admission import (
    ResearchReviewOpportunityEngine,
    ScreeningAdmissionPolicy,
)
from screening.orchestration import (
    FullUniverseScreeningOrchestrator as StrictFullUniverseScreeningOrchestrator,
)
from screening.orchestration import (
    FullUniverseScreeningRequest as StrictFullUniverseScreeningRequest,
)


class MatureMarketUniverseBuilder(StrictVersion1UniverseBuilder):
    """Build a broad screening universe without granting investment authority."""

    def __init__(self, policy=None) -> None:
        super().__init__(policy=policy or ScreeningAdmissionPolicy())


@dataclass(frozen=True, slots=True)
class FullUniverseScreeningRequest(StrictFullUniverseScreeningRequest):
    """Default to instrument-level quarantine instead of whole-cycle failure."""

    require_complete_metric_coverage: bool = False


class FullUniverseScreeningOrchestrator(StrictFullUniverseScreeningOrchestrator):
    """Inject mature-market admission and research-review qualification."""

    def __init__(
        self,
        *,
        universe_builder=None,
        opportunity_engine=None,
        **kwargs,
    ) -> None:
        super().__init__(
            universe_builder=universe_builder or MatureMarketUniverseBuilder(),
            opportunity_engine=(
                opportunity_engine or ResearchReviewOpportunityEngine()
            ),
            **kwargs,
        )


__all__ = [
    "FullUniverseScreeningOrchestrator",
    "FullUniverseScreeningRequest",
    "MatureMarketUniverseBuilder",
]
