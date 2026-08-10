from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cio.models import CIOAction
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


def _decision_marker(
    *,
    stage: str,
    target: float | None,
    hard=(),
    soft=(),
    action=CIOAction.WATCH,
):
    payload = {
        "conviction_stage": stage,
        "conviction_target_weight": target,
        "hard_blockers": list(hard),
        "soft_constraints": list(soft),
    }
    return SimpleNamespace(
        action=action,
        monitoring_indicators=(
            "global-rotation-context.v1:"
            + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        ),
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
            expected_return_improvement=0.0,
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
    assert accountability.construction_expected_return_improvement == 0.0


def test_post_specialist_hard_blockers_explain_cash_without_calling_it_economic():
    decision = _decision_marker(
        stage="blocked",
        target=None,
        hard=("portfolio implementation blocks remain unresolved",),
        soft=("growth ensemble remains at observe",),
    )
    result = SimpleNamespace(
        decisions=(decision,),
        construction=None,
        cycle_disposition=None,
    )
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:post-specialist-block",
        context=_context(),
        result=result,
    )
    assert (
        accountability.classification
        is ResidualCashClassification.HARD_CONSTRAINT_FORCED
    )
    assert accountability.hard_blocked_candidate_count == 1
    assert accountability.hard_blocker_count == 1
    assert accountability.soft_constraint_count == 1
    assert accountability.conviction_stage_counts == (("blocked", 1),)
    assert accountability.indicated_conviction_weight == 0.0


def test_conviction_diagnostics_record_deployable_weight_and_stage():
    decision = _decision_marker(
        stage="provisional",
        target=0.025,
        soft=("success probability is below the full-conviction threshold",),
        action=CIOAction.BUY,
    )
    result = SimpleNamespace(
        decisions=(decision,),
        construction=SimpleNamespace(
            target_cash_weight=0.775,
            blocks=(),
            expected_return_improvement=0.004,
        ),
        cycle_disposition=None,
    )
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:provisional",
        context=_context(),
        result=result,
    )
    assert (
        accountability.classification
        is ResidualCashClassification.DEPLOYED_WITH_RESIDUAL
    )
    assert accountability.conviction_stage_counts == (("provisional", 1),)
    assert accountability.indicated_conviction_weight == 0.025
    assert accountability.soft_constraint_count == 1
    assert accountability.construction_expected_return_improvement == 0.004


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
