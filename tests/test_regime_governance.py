"""Tests for the governed regime-to-committee bridge."""

from __future__ import annotations

from datetime import date, datetime, timezone

from committee import (
    DissentDisposition,
    RegimeGovernanceOutcome,
    RegimeGovernanceWorkflow,
    StructuredDissent,
    build_regime_recommendation,
)
from data import (
    AvailabilityBasis,
    DataQualityState,
    NormalizedObservation,
    ObservationProvenance,
    ObservationQuery,
    ProviderError,
)
from intelligence.recommendation import (
    RecommendationAction,
    RecommendationLevel,
)
from intelligence.regime_pipeline import InstitutionalRegimePipeline
from journal import (
    JournalEventType,
    SQLiteAppendOnlyJournal,
)


AS_OF = datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc)


def _observation(
    query: ObservationQuery,
    value: float,
    observation_date: date,
) -> NormalizedObservation:
    series = query.series
    return NormalizedObservation(
        indicator=series.indicator,
        category=series.category,
        value=value,
        unit=series.unit,
        frequency=series.frequency,
        observation_date=observation_date,
        provenance=ObservationProvenance(
            provider="FRED",
            series_identifier=series.provider_series_identifier,
            released_at=datetime(
                observation_date.year,
                observation_date.month,
                min(observation_date.day + 15, 28),
                12,
                tzinfo=timezone.utc,
            ),
            retrieved_at=AS_OF,
            quality_state=DataQualityState.LIVE,
            availability_basis=(
                AvailabilityBasis.PROVIDER_TIMESTAMP
            ),
        ),
        transformation=series.transformation,
        importance=series.importance,
        stale_after=series.stale_after,
    )


class RegimeProvider:
    """Complete deterministic fixture with optional missing series."""

    name = "FRED"

    def __init__(
        self,
        unavailable: set[str] | None = None,
    ) -> None:
        self.unavailable = unavailable or set()

    def fetch(
        self,
        query: ObservationQuery,
    ) -> tuple[NormalizedObservation, ...]:
        series_id = query.series.provider_series_identifier
        if series_id in self.unavailable:
            raise ProviderError(f"{series_id} unavailable")
        prior = date(2024, 12, 1)
        current = date(2025, 12, 1)
        values = {
            "INDPRO": (
                _observation(query, 100.0, prior),
                _observation(query, 102.0, current),
            ),
            "CPIAUCSL": (
                _observation(query, 300.0, prior),
                _observation(query, 307.5, current),
            ),
            "FEDFUNDS": (_observation(query, 3.0, current),),
            "WALCL": (
                _observation(query, 100.0, prior),
                _observation(query, 104.0, current),
            ),
            "STLFSI4": (_observation(query, 0.2, current),),
        }
        return values[series_id]


def _run(
    unavailable: set[str] | None = None,
):
    return InstitutionalRegimePipeline(
        RegimeProvider(unavailable)
    ).run(as_of=AS_OF)


def test_builds_committee_ready_macro_recommendation() -> None:
    recommendation = build_regime_recommendation(_run())

    assert recommendation.level is RecommendationLevel.MACRO
    assert recommendation.action is RecommendationAction.OVERWEIGHT
    assert recommendation.target == "diversified_risk_assets"
    assert recommendation.confidence == 0.79
    assert recommendation.supporting_evidence
    assert recommendation.invalidation_conditions


def test_complete_evidence_reaches_existing_committee() -> None:
    decision = RegimeGovernanceWorkflow(
        clock=lambda: AS_OF
    ).evaluate(_run())

    assert decision.outcome is RegimeGovernanceOutcome.APPROVE
    assert decision.committee_result is not None
    assert decision.committee_result.decision.opinion_count == 6
    assert decision.no_action is None


def test_coverage_gate_records_formal_no_action() -> None:
    class CommitteeMustNotRun:
        def evaluate(self, recommendation):  # pragma: no cover
            raise AssertionError("committee should not run")

    decision = RegimeGovernanceWorkflow(
        committee_workflow=CommitteeMustNotRun(),
        clock=lambda: AS_OF,
    ).evaluate(_run({"WALCL", "STLFSI4"}))

    assert decision.outcome is RegimeGovernanceOutcome.NO_ACTION
    assert decision.committee_result is None
    assert decision.no_action is not None
    assert decision.no_action.reason.value == "insufficient_evidence"
    assert decision.no_action.review_at > decision.decided_at


def test_material_open_dissent_escalates_approved_result() -> None:
    dissent = StructuredDissent(
        member="Risk Chair",
        specialty="portfolio risk",
        position="Do not increase risk yet.",
        rationale="Tail-risk evidence remains unresolved.",
        evidence_identifiers=("stress-scenario-1",),
        resolution_conditions=("Re-run the stress scenario.",),
        materiality=0.8,
        recorded_at=AS_OF,
        disposition=DissentDisposition.OPEN,
    )

    decision = RegimeGovernanceWorkflow(
        clock=lambda: AS_OF
    ).evaluate(_run(), dissents=(dissent,))

    assert decision.outcome is RegimeGovernanceOutcome.ESCALATE
    assert decision.committee_result is not None
    assert decision.dissents == (dissent,)


def test_journal_links_regime_run_and_decision(tmp_path) -> None:
    run = _run()
    workflow = RegimeGovernanceWorkflow(clock=lambda: AS_OF)
    decision = workflow.evaluate(
        run,
        regime_run_identifier="regime-run-14",
    )
    journal = SQLiteAppendOnlyJournal(
        tmp_path / "journal.db",
        clock=lambda: AS_OF,
        identifier_factory=iter(("event-run", "event-decision")).__next__,
    )

    journal.append_regime_run(
        run,
        run_identifier="regime-run-14",
        code_version="test-sha",
    )
    event = journal.append_regime_committee_decision(decision)

    assert event.event_type is (
        JournalEventType.REGIME_COMMITTEE_DECISION
    )
    assert event.aggregate_identifier == "regime-run-14"
    assert event.payload["outcome"] == "approve"
    assert event.payload["committee"]["opinion_count"] == 6
    assert len(event.payload["committee"]["opinions"]) == 6
    assert (
        event.payload["committee"]["statistics"]["supportive_count"]
        == 6
    )
    assert len(journal.events(
        aggregate_identifier="regime-run-14"
    )) == 2
    assert journal.verify_integrity()
