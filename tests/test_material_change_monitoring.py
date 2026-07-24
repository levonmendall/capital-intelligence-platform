"""Tests for continuous analysis and selective portfolio alerts."""

from __future__ import annotations

from datetime import date, datetime, timezone

from committee import RegimeGovernanceWorkflow
from data import ObservationQuery, ProviderError
from intelligence.regime_pipeline import InstitutionalRegimePipeline
from journal import JournalEventType, SQLiteAppendOnlyJournal
from monitoring import (
    AlertLevel,
    ChangeCategory,
    ContinuousRegimeMonitor,
    PortfolioImpactDirection,
    RegimeMaterialChangeEngine,
    ReviewState,
)
from tests.test_regime_governance import (
    RegimeProvider,
    _observation,
)


FIRST_AS_OF = datetime(
    2026,
    1,
    31,
    23,
    59,
    tzinfo=timezone.utc,
)
SECOND_AS_OF = datetime(
    2026,
    2,
    10,
    23,
    59,
    tzinfo=timezone.utc,
)


class ChangedRegimeProvider(RegimeProvider):
    """Fixture that can change growth or liquidity."""

    def __init__(
        self,
        *,
        growth_value: float = 102.0,
        liquidity_value: float = 104.0,
        current_date: date = date(2025, 12, 1),
        unavailable: set[str] | None = None,
    ) -> None:
        super().__init__(unavailable)
        self.growth_value = growth_value
        self.liquidity_value = liquidity_value
        self.current_date = current_date

    def fetch(self, query: ObservationQuery):
        series_id = query.series.provider_series_identifier
        if series_id in self.unavailable:
            raise ProviderError(f"{series_id} unavailable")
        current = self.current_date
        prior = date(
            current.year - 1,
            current.month,
            current.day,
        )
        values = {
            "INDPRO": (
                _observation(query, 100.0, prior),
                _observation(
                    query,
                    self.growth_value,
                    current,
                ),
            ),
            "CPIAUCSL": (
                _observation(query, 300.0, prior),
                _observation(query, 307.5, current),
            ),
            "FEDFUNDS": (
                _observation(query, 3.0, current),
            ),
            "WALCL": (
                _observation(query, 100.0, prior),
                _observation(
                    query,
                    self.liquidity_value,
                    current,
                ),
            ),
            "STLFSI4": (
                _observation(query, 0.2, current),
            ),
        }
        return values[series_id]


def _run(provider, *, as_of):
    return InstitutionalRegimePipeline(provider).run(as_of=as_of)


def _decision(run):
    return RegimeGovernanceWorkflow(
        clock=lambda: run.as_of
    ).evaluate(run)


def _compare(previous_run, current_run):
    return RegimeMaterialChangeEngine(
        clock=lambda: SECOND_AS_OF
    ).compare(
        previous_run,
        current_run,
        _decision(previous_run),
        _decision(current_run),
    )


def test_unchanged_analysis_is_recorded_but_silent() -> None:
    previous = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    current = _run(
        ChangedRegimeProvider(current_date=date(2026, 1, 28)),
        as_of=SECOND_AS_OF,
    )

    assessment = _compare(previous, current)

    assert assessment.state is ReviewState.UNCHANGED
    assert assessment.alert_level is AlertLevel.SILENT
    assert not assessment.should_alert
    assert assessment.changes == ()
    assert assessment.headline == "Market view unchanged"
    assert (
        assessment.portfolio_impact.direction
        is PortfolioImpactDirection.HOLD
    )
    assert (
        assessment.explanation
        == "The market view is unchanged. Keep the portfolio as it is."
    )


def test_one_material_signal_is_monitored_without_alert() -> None:
    previous = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    current = _run(
        ChangedRegimeProvider(
            liquidity_value=96.0,
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )

    assessment = _compare(previous, current)

    assert assessment.state is ReviewState.MONITOR
    assert assessment.alert_level is AlertLevel.SILENT
    assert not assessment.should_alert
    assert any(
        change.category is ChangeCategory.SIGNAL
        and "Liquidity" in change.summary
        for change in assessment.changes
    )
    assert (
        assessment.explanation
        == "Some market evidence moved, but not enough to change "
        "the portfolio."
    )


def test_contraction_invalidates_view_and_alerts_to_reduce_risk() -> None:
    previous = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    current = _run(
        ChangedRegimeProvider(
            growth_value=95.0,
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )

    assessment = _compare(previous, current)

    assert assessment.state is ReviewState.PRIOR_VIEW_INVALIDATED
    assert assessment.alert_level is AlertLevel.URGENT
    assert assessment.should_alert
    assert (
        assessment.portfolio_impact.direction
        is PortfolioImpactDirection.REDUCE_RISK
    )
    assert "equities" in (
        assessment.portfolio_impact.affected_exposures
    )
    assert "crypto risk budget" in (
        assessment.portfolio_impact.affected_exposures
    )
    assert assessment.headline == "Risk review is urgent"


def test_missing_evidence_alerts_without_recommending_a_trade() -> None:
    previous = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    current = _run(
        ChangedRegimeProvider(
            unavailable={"WALCL", "STLFSI4"},
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )

    assessment = _compare(previous, current)

    assert assessment.state is ReviewState.REVIEW_REQUIRED
    assert assessment.alert_level is AlertLevel.NOTIFY
    assert assessment.should_alert
    assert (
        assessment.portfolio_impact.direction
        is PortfolioImpactDirection.REVIEW
    )
    assert any(
        change.category is ChangeCategory.DATA_QUALITY
        for change in assessment.changes
    )
    assert "Keep the portfolio steady" in assessment.explanation


def test_silent_analysis_is_preserved_in_journal(tmp_path) -> None:
    previous = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    current = _run(
        ChangedRegimeProvider(current_date=date(2026, 1, 28)),
        as_of=SECOND_AS_OF,
    )
    assessment = _compare(previous, current)
    journal = SQLiteAppendOnlyJournal(
        tmp_path / "journal.db",
        clock=lambda: SECOND_AS_OF,
        identifier_factory=lambda: "event-change",
    )

    event = journal.append_market_change_assessment(assessment)

    assert event.event_type is (
        JournalEventType.MARKET_CHANGE_ASSESSMENT
    )
    assert event.payload["should_alert"] is False
    assert event.payload["state"] == "unchanged"
    assert event.payload["portfolio_impact"]["direction"] == "hold"
    assert event.aggregate_identifier == "market-monitor:regime"
    assert journal.verify_integrity()


def test_monitor_records_every_cycle_and_alerts_only_material_change(
    tmp_path,
) -> None:
    previous = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    previous_decision = _decision(previous)
    journal = SQLiteAppendOnlyJournal(
        tmp_path / "monitor.db",
        clock=lambda: SECOND_AS_OF,
        identifier_factory=iter(
            ("silent-event", "urgent-event")
        ).__next__,
    )
    alerts = []
    quiet_monitor = ContinuousRegimeMonitor(
        InstitutionalRegimePipeline(
            ChangedRegimeProvider(
                current_date=date(2026, 1, 28)
            )
        ),
        governance=RegimeGovernanceWorkflow(
            clock=lambda: SECOND_AS_OF
        ),
        change_engine=RegimeMaterialChangeEngine(
            clock=lambda: SECOND_AS_OF
        ),
        assessment_sink=(
            journal.append_market_change_assessment
        ),
        alert_sink=alerts.append,
    )

    quiet = quiet_monitor.run_cycle(
        as_of=SECOND_AS_OF,
        previous_run=previous,
        previous_decision=previous_decision,
    )

    assert not quiet.change_assessment.should_alert
    assert alerts == []
    assert len(journal.events()) == 1

    urgent_monitor = ContinuousRegimeMonitor(
        InstitutionalRegimePipeline(
            ChangedRegimeProvider(
                growth_value=95.0,
                current_date=date(2026, 1, 28),
            )
        ),
        governance=RegimeGovernanceWorkflow(
            clock=lambda: SECOND_AS_OF
        ),
        change_engine=RegimeMaterialChangeEngine(
            clock=lambda: SECOND_AS_OF
        ),
        assessment_sink=(
            journal.append_market_change_assessment
        ),
        alert_sink=alerts.append,
    )

    urgent = urgent_monitor.run_cycle(
        as_of=SECOND_AS_OF,
        previous_run=previous,
        previous_decision=previous_decision,
    )

    assert urgent.change_assessment.should_alert
    assert alerts == [urgent.change_assessment]
    assert len(journal.events()) == 2
