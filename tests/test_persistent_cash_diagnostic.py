"""Behavioral coverage for non-authoritative persistent-cash instrumentation."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from application import ProductionCanonicalCIOExecutor
from application.cio_cycle import (
    CandidateExposureProfile,
    CanonicalCIOCycle,
    CyclePortfolioState,
)
from cio.persistence import (
    CIOJournalEventType,
    SQLiteCIOJournal,
    serialize_candidate_decision,
    serialize_opportunity_queue,
)
from evaluation.persistent_cash import (
    CashNoActionReason,
    FunnelStage,
    append_persistent_cash_diagnostic,
    build_persistent_cash_diagnostic,
    summarize_persistent_cash_journal,
)
from screening import FullUniverseScreeningPublication
from tests.test_canonical_cio_cycle import (
    AS_OF,
    _candidate,
    _construction_policy,
    _context,
    _opportunity_context,
    _portfolio,
)
from tests.test_canonical_production_context_adapter import (
    AS_OF as PRODUCTION_AS_OF,
    _adapter,
)


def _publication(candidate, result, *, cycle_identifier: str):
    return FullUniverseScreeningPublication(
        identifier=f"publication:{cycle_identifier}",
        cycle_identifier=cycle_identifier,
        published_at=AS_OF - timedelta(minutes=1),
        security_master_catalog_identifier="catalog:test",
        security_master_snapshot_identifier="security-master:test",
        universe_snapshot_identifier="universe:test",
        opportunity_context_identifier=result.opportunity_queue.context_identifier,
        eligible_instrument_count=1,
        screened_instrument_count=1,
        candidate_count=1,
        excluded_count=0,
        candidate_payloads=(serialize_candidate_decision(candidate),),
        exclusions=(),
        opportunity_queue_payload=serialize_opportunity_queue(
            result.opportunity_queue,
            occurred_at=AS_OF,
        ),
    )


def _all_cash_portfolio(candidate):
    return CyclePortfolioState(
        identifier="portfolio:all-cash",
        as_of=AS_OF,
        portfolio_value=250_000.0,
        cash_weight=1.0,
        cash_expected_return=0.04,
        positions=(),
        exposure_profiles=(
            CandidateExposureProfile(
                candidate_identifier=candidate.identifier,
                sector="Diversified",
                factor_loadings=(("market", 0.80),),
                correlation_bucket="broad-market",
            ),
        ),
    )


def test_qualified_candidate_reconciles_every_pre_execution_stage() -> None:
    candidate = _candidate("QUAL")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    ).run(
        identifier="cycle:diagnostic-qualified",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
        code_version="commit:diagnostic",
    )
    diagnostic = build_persistent_cash_diagnostic(
        publication=_publication(
            candidate,
            result,
            cycle_identifier="screening:diagnostic-qualified",
        ),
        candidates=(candidate,),
        context_candidate_identifiers=(candidate.identifier,),
        result=result,
        cash_weight_before=0.20,
        minimum_evidence_score=0.70,
        minimum_evidence_dimension=0.50,
        code_version="commit:diagnostic",
    )

    observation = diagnostic.observations[0]
    assert FunnelStage.SIX_SPECIALIST_ANALYSIS in observation.reached_stages
    assert FunnelStage.CIO_QUALIFICATION in observation.reached_stages
    assert FunnelStage.RISK_ADJUSTED_INITIAL_TARGET in observation.reached_stages
    assert FunnelStage.NONZERO_FINAL_TARGET in observation.reached_stages
    assert FunnelStage.PAPER_IMPLEMENTATION not in observation.reached_stages
    assert observation.paper_implementation_state == "not_observed_at_decision_boundary"
    assert observation.primary_reason is None
    assert diagnostic.primary_reason is None
    assert not diagnostic.implementation_observation_complete


def test_all_cash_rejection_records_cash_hurdle_without_lowering_it() -> None:
    weak = _candidate(
        "WEAK",
        base_return=0.01,
        bull_return=0.04,
        bear_return=-0.20,
    )
    weak = replace(weak, probability_of_success=0.0)
    portfolio = _all_cash_portfolio(weak)
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    ).run(
        identifier="cycle:diagnostic-cash",
        candidates=(weak,),
        opportunity_context=_opportunity_context(cash_weight=1.0),
        specialist_contexts=(),
        portfolio=portfolio,
        code_version="commit:diagnostic",
    )
    diagnostic = build_persistent_cash_diagnostic(
        publication=_publication(
            weak,
            result,
            cycle_identifier="screening:diagnostic-cash",
        ),
        candidates=(weak,),
        context_candidate_identifiers=(),
        result=result,
        cash_weight_before=1.0,
        minimum_evidence_score=0.70,
        minimum_evidence_dimension=0.50,
        code_version="commit:diagnostic",
    )

    observation = diagnostic.observations[0]
    assert observation.primary_reason is CashNoActionReason.FAILURE_TO_EXCEED_CASH_HURDLE
    assert CashNoActionReason.INSUFFICIENT_EXPECTED_RETURN in observation.contributing_reasons
    assert FunnelStage.SCREENING not in observation.reached_stages
    assert diagnostic.portfolio_remained_all_cash_at_construction
    assert diagnostic.primary_reason is CashNoActionReason.FAILURE_TO_EXCEED_CASH_HURDLE
    assert result.decisions == ()
    assert result.construction is None


def test_diagnostic_is_idempotent_append_only_and_summarizes_available_cycles(
    tmp_path,
) -> None:
    candidate = _candidate("QUAL")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    ).run(
        identifier="cycle:diagnostic-journal",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
    )
    diagnostic = build_persistent_cash_diagnostic(
        publication=_publication(
            candidate,
            result,
            cycle_identifier="screening:diagnostic-journal",
        ),
        candidates=(candidate,),
        context_candidate_identifiers=(candidate.identifier,),
        result=result,
        cash_weight_before=0.20,
        minimum_evidence_score=0.70,
        minimum_evidence_dimension=0.50,
        code_version="commit:diagnostic",
    )
    journal = SQLiteCIOJournal(tmp_path / "cio.db")

    first = append_persistent_cash_diagnostic(journal, diagnostic)
    second = append_persistent_cash_diagnostic(journal, diagnostic)
    summary = summarize_persistent_cash_journal(journal)

    assert first.content_hash == second.content_hash
    assert journal.count() == 1
    assert journal.verify_integrity()
    assert summary["available_cycle_count"] == 1
    assert summary["paper_fill_event_count"] == 0
    assert summary["authority"]["investment_behavior_changed"] is False


def test_diagnostic_failure_cannot_change_cio_result(tmp_path, monkeypatch) -> None:
    candidate, screening_store, adapter = _adapter(tmp_path)
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(journal=journal),
        screening_store=screening_store,
        context_provider=adapter,
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("diagnostic storage unavailable")

    monkeypatch.setattr(
        "evaluation.persistent_cash.append_persistent_cash_diagnostic",
        fail,
    )
    result = executor.run(as_of=PRODUCTION_AS_OF)

    assert result.decisions
    assert result.decisions[0].candidate_identifier == candidate.identifier
    assert not journal.events(
        event_type=CIOJournalEventType.PERSISTENT_CASH_DIAGNOSTIC,
    )
    assert journal.verify_integrity()


def test_active_production_executor_appends_one_diagnostic_event(tmp_path) -> None:
    _, screening_store, adapter = _adapter(tmp_path)
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(journal=journal),
        screening_store=screening_store,
        context_provider=adapter,
    )

    result = executor.run(as_of=PRODUCTION_AS_OF)
    events = journal.events(
        event_type=CIOJournalEventType.PERSISTENT_CASH_DIAGNOSTIC,
    )

    assert len(events) == 1
    assert events[0].aggregate_identifier == result.identifier
    assert events[0].payload["authority"]["diagnostic_only"] is True
    assert journal.verify_integrity()
