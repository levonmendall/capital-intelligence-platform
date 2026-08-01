"""Regression coverage for runtime context and hysteresis continuity blockers."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from application.cio_cycle import CanonicalCIOCycle
from cio import CIOAction, ChiefInvestmentOfficer
from cio.persistence import SQLiteCIOJournal
from opportunity import AlternativeKind, OpportunityEngine
from screening import SQLiteFullUniverseScreeningStore
from tests.test_canonical_cio_cycle import (
    _candidate as _cycle_candidate,
    _construction_policy,
    _portfolio,
)
from tests.test_decision_quality_reconciliation import (
    _candidate,
    _context,
    _packet,
)
from tests.test_production_context_publication_runtime import (
    _bootstrap_cash_portfolio,
    _evidence,
    _equity_discovery_probe,
    _provider,
    _readiness,
    _settings,
)
from production_context_publication_runtime import prepare_production_context_for_cycle
from types import SimpleNamespace
from datetime import datetime, timezone


def _base_decision(candidate):
    qualification = OpportunityEngine().qualify(candidate, _context())
    return ChiefInvestmentOfficer().synthesize(
        candidate,
        qualification.universe,
        _packet(candidate, duplicate_origins=False),
        capital_comparison=qualification.capital_comparison,
    )


def test_deferred_buy_counts_as_supportive_persistence_across_candidate_ids(tmp_path) -> None:
    journal = SQLiteCIOJournal(tmp_path / "cio.db")
    candidate = _candidate("ENTRY")
    decision = _base_decision(candidate)
    deferred = replace(
        decision,
        action=CIOAction.WATCH,
        recommended_position_weight=None,
        funding_source=None,
        hysteresis_applied=True,
        deferred_action=CIOAction.BUY,
        persistence_cycles=1,
    )
    journal.append_candidate(candidate)
    event = journal.append_decision(deferred)
    assert event.payload["deferred_action"] == CIOAction.BUY.value

    later = replace(
        candidate,
        identifier="candidate:entry:later",
        as_of=candidate.as_of + timedelta(days=1),
        review_at=candidate.review_at + timedelta(days=1),
    )
    context = journal.prior_decision_contexts((later,), as_of=later.as_of)[0]

    assert context.candidate_identifier == later.identifier
    assert context.consecutive_supportive_cycles == 1
    assert context.consecutive_opposing_cycles == 0


def test_deferred_reduce_counts_as_opposing_persistence_across_candidate_ids(tmp_path) -> None:
    journal = SQLiteCIOJournal(tmp_path / "cio.db")
    candidate = replace(
        _candidate("REDUCE"),
        current_portfolio_weight=0.08,
        maximum_position_weight=0.08,
    )
    decision = _base_decision(_candidate("REDUCE"))
    deferred = replace(
        decision,
        identifier="cio-decision:deferred-reduce",
        candidate_identifier=candidate.identifier,
        action=CIOAction.HOLD,
        recommended_position_weight=None,
        funding_source=None,
        hysteresis_applied=True,
        deferred_action=CIOAction.REDUCE,
        persistence_cycles=1,
    )
    journal.append_candidate(candidate)
    journal.append_decision(deferred)

    later = replace(
        candidate,
        identifier="candidate:reduce:later",
        as_of=candidate.as_of + timedelta(days=1),
        review_at=candidate.review_at + timedelta(days=1),
    )
    context = journal.prior_decision_contexts((later,), as_of=later.as_of)[0]

    assert context.consecutive_supportive_cycles == 0
    assert context.consecutive_opposing_cycles == 1


def test_portfolio_preview_uses_final_effective_capital_alternative() -> None:
    candidate = _cycle_candidate("QUAL")
    cycle = CanonicalCIOCycle(construction_policy=_construction_policy())

    preview = cycle._preview_portfolio(
        candidate=candidate,
        rank=1,
        portfolio=_portfolio((candidate,)),
        effective_opportunity_cost=0.18,
    )

    assert preview.opportunity_cost_return == pytest.approx(0.18)


def test_runtime_context_reconstructs_persisted_competitive_alternatives(tmp_path) -> None:
    settings = _settings(tmp_path)
    scheduled_for = datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc)
    decision_time = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    _bootstrap_cash_portfolio(
        settings,
        as_of=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),
    )

    result = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=lambda _universe: _readiness(decision_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-28", value=4.25),
        evidence_probe=lambda _universe, _as_of: _evidence(decision_time),
        equity_discovery_probe=_equity_discovery_probe,
        clock=lambda: decision_time,
    )
    assert result.ready

    store = SQLiteFullUniverseScreeningStore(
        settings.full_universe_screening_database
    )
    publication = store.publication(result.screening_cycle_identifier)
    assert publication is not None
    persisted = tuple(
        publication.opportunity_queue_payload[
            "candidate_alternative_identifiers"
        ]
    )
    context = _provider(settings, tmp_path).load_context(as_of=decision_time)
    runtime = tuple(
        item.identifier
        for item in context.opportunity_context.alternatives
        if item.kind is AlternativeKind.QUALIFIED_CANDIDATE
    )

    assert runtime == persisted
    alternatives = tuple(
        item
        for item in context.opportunity_context.alternatives
        if item.kind is AlternativeKind.QUALIFIED_CANDIDATE
    )
    assert alternatives
    assert all(item.implementation_cost_return == 0.0 for item in alternatives)
    assert all(item.evidence_quality == 1.0 for item in alternatives)
    assert all(item.liquidity_score == 1.0 for item in alternatives)
