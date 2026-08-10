from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from portfolio.global_rotation import (
    CashCompetitionState,
    GlobalOpportunityDomain,
    GlobalOpportunitySignal,
    GlobalRotationContext,
)
from portfolio.global_rotation_persistence import (
    ResidualCashClassification,
    SQLiteGlobalRotationStore,
    build_global_cash_accountability,
)

NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def _context(*, cash_state=CashCompetitionState.DEPLOYMENT_OPPORTUNITY):
    return GlobalRotationContext(
        as_of=NOW,
        signals=(
            GlobalOpportunitySignal(
                candidate_identifier="candidate:usd",
                domain=GlobalOpportunityDomain.CURRENCY,
                rank=1,
                score=0.82,
                leadership_state="leading",
                leadership_score=0.82,
                mispriced_change_state="constructive_mispriced_change",
                mispriced_change_score=0.55,
                forward_impulse=0.04,
                expected_return_edge=0.05,
                evidence_score=0.90,
                evidence_identifiers=("evidence:usd",),
            ),
        ),
        cash_expected_return=0.04,
        minimum_cash_weight=0.05,
        current_cash_weight=0.80,
        excess_cash_weight=0.75,
        cash_competition_state=cash_state,
    )


def test_cash_accountability_marks_unexplained_abstention_when_opportunity_existed():
    result = SimpleNamespace(decisions=(), construction=None, cycle_disposition=None)
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:cash",
        context=_context(),
        result=result,
    )
    assert (
        accountability.classification
        is ResidualCashClassification.UNEXPLAINED_RESIDUAL
    )
    assert accountability.residual_excess_cash_weight == 0.75
    assert accountability.strongest_domain == "currency"


def test_cash_accountability_distinguishes_construction_block_from_unexplained_cash():
    result = SimpleNamespace(
        decisions=(),
        construction=SimpleNamespace(
            target_cash_weight=0.80,
            blocks=("tail-risk limit",),
        ),
        cycle_disposition=None,
    )
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:blocked",
        context=_context(),
        result=result,
    )
    assert (
        accountability.classification
        is ResidualCashClassification.HARD_CONSTRAINT_FORCED
    )
    assert accountability.construction_block_count == 1


def test_evidence_or_authority_empty_queue_is_forced_cash_not_economic_win():
    result = SimpleNamespace(
        decisions=(),
        construction=None,
        cycle_disposition=SimpleNamespace(
            classification="evidence_or_authority_block"
        ),
    )
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:evidence-blocked",
        context=_context(cash_state=CashCompetitionState.CASH_LEADING_ESTIMATE),
        result=result,
    )
    assert (
        accountability.classification
        is ResidualCashClassification.HARD_CONSTRAINT_FORCED
    )
    assert accountability.cycle_disposition_classification == "evidence_or_authority_block"
    assert "Cash did not win" in accountability.explanation


def test_economically_unqualified_empty_queue_can_remain_cash_estimate():
    result = SimpleNamespace(
        decisions=(),
        construction=None,
        cycle_disposition=SimpleNamespace(classification="economically_unqualified"),
    )
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:economic-cash",
        context=_context(cash_state=CashCompetitionState.CASH_LEADING_ESTIMATE),
        result=result,
    )
    assert (
        accountability.classification
        is ResidualCashClassification.ECONOMIC_WIN_ESTIMATE
    )
    assert accountability.cycle_disposition_classification == "economically_unqualified"


def test_cash_accountability_store_is_append_only_idempotent_and_stream_verifiable(
    tmp_path,
):
    store = SQLiteGlobalRotationStore(tmp_path / "journal.sqlite")
    context = _context()
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:persist",
        context=context,
        result=SimpleNamespace(decisions=(), construction=None, cycle_disposition=None),
    )
    first = store.append(
        cycle_identifier="cycle:persist",
        context=context,
        accountability=accountability,
        code_version="test-sha",
    )
    second = store.append(
        cycle_identifier="cycle:persist",
        context=context,
        accountability=accountability,
        code_version="test-sha",
    )
    assert first == second
    assert store.verify_integrity() is True
    with store._connect() as connection:
        with pytest.raises(Exception):
            connection.execute(
                "UPDATE global_rotation_events SET cycle_identifier='changed' WHERE sequence=1"
            )
