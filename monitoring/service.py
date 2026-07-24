"""Application service for continuous analysis and selective delivery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from committee.regime_governance import (
    RegimeCommitteeDecision,
    RegimeGovernanceWorkflow,
)
from intelligence.regime_pipeline import (
    InstitutionalRegimePipeline,
    InstitutionalRegimeRun,
)
from monitoring.material_change import (
    MarketChangeAssessment,
    RegimeMaterialChangeEngine,
)


@dataclass(frozen=True, slots=True)
class RegimeMonitoringCycle:
    """Complete output from one scheduled monitoring iteration."""

    run: InstitutionalRegimeRun
    decision: RegimeCommitteeDecision
    change_assessment: MarketChangeAssessment

    def __post_init__(self) -> None:
        if not isinstance(self.run, InstitutionalRegimeRun):
            raise TypeError("run must be an InstitutionalRegimeRun")
        if not isinstance(self.decision, RegimeCommitteeDecision):
            raise TypeError(
                "decision must be a RegimeCommitteeDecision"
            )
        if not isinstance(
            self.change_assessment,
            MarketChangeAssessment,
        ):
            raise TypeError(
                "change_assessment must be a "
                "MarketChangeAssessment"
            )
        if self.run.as_of != self.change_assessment.current_as_of:
            raise ValueError(
                "run must match the current change assessment"
            )


class ContinuousRegimeMonitor:
    """Run every cycle, record every result, and alert selectively."""

    def __init__(
        self,
        pipeline: InstitutionalRegimePipeline,
        *,
        governance: RegimeGovernanceWorkflow | None = None,
        change_engine: RegimeMaterialChangeEngine | None = None,
        assessment_sink: (
            Callable[[MarketChangeAssessment], object] | None
        ) = None,
        alert_sink: (
            Callable[[MarketChangeAssessment], object] | None
        ) = None,
    ) -> None:
        if not isinstance(pipeline, InstitutionalRegimePipeline):
            raise TypeError(
                "pipeline must be an InstitutionalRegimePipeline"
            )
        self.pipeline = pipeline
        self.governance = governance or RegimeGovernanceWorkflow()
        self.change_engine = (
            change_engine or RegimeMaterialChangeEngine()
        )
        self.assessment_sink = assessment_sink
        self.alert_sink = alert_sink

    def run_cycle(
        self,
        *,
        as_of: datetime,
        previous_run: InstitutionalRegimeRun,
        previous_decision: RegimeCommitteeDecision,
    ) -> RegimeMonitoringCycle:
        """Execute analysis regardless of whether notification is needed."""

        current_run = self.pipeline.run(as_of=as_of)
        current_decision = self.governance.evaluate(current_run)
        assessment = self.change_engine.compare(
            previous_run,
            current_run,
            previous_decision,
            current_decision,
        )
        if self.assessment_sink is not None:
            self.assessment_sink(assessment)
        if assessment.should_alert and self.alert_sink is not None:
            self.alert_sink(assessment)
        return RegimeMonitoringCycle(
            run=current_run,
            decision=current_decision,
            change_assessment=assessment,
        )


__all__ = [
    "ContinuousRegimeMonitor",
    "RegimeMonitoringCycle",
]
