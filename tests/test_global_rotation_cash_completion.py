from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

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


def _context() -> GlobalRotationContext:
    return GlobalRotationContext(
        as_of=NOW,
        signals=(
            GlobalOpportunitySignal(
                candidate_identifier="candidate:HBM",
                domain=GlobalOpportunityDomain.EQUITY,
                rank=1,
                score=0.84,
                leadership_state="emerging",
                leadership_score=0.80,
                mispriced_change_state="constructive_mispriced_change",
                mispriced_change_score=0.60,
                forward_impulse=0.04,
                expected_return_edge=0.06,
                evidence_score=0.90,
                evidence_identifiers=("evidence:HBM",),
                causal_stage="accelerating_successor",
                causal_score=0.81,
                transition_probability=0.79,
                hierarchy_strength=0.86,
                hierarchy_path=("equity", "US / USD", "semiconductors / AI", "memory", "HBM"),
                longitudinal_state="rotating_in",
                score_change=0.11,
                rank_change=3,
            ),
        ),
        cash_expected_return=0.04,
        minimum_cash_weight=0.05,
        current_cash_weight=0.80,
        excess_cash_weight=0.75,
        cash_competition_state=CashCompetitionState.DEPLOYMENT_OPPORTUNITY,
    )


def test_partial_positive_trade_does_not_hide_material_unfilled_optimizer_cash():
    decision = SimpleNamespace(
        action=CIOAction.BUY,
        monitoring_indicators=(
            'global-rotation-context.v1:{"conviction_stage":"provisional","conviction_target_weight":0.025,"hard_blockers":[],"soft_constraints":[]}',
        ),
    )
    trade = SimpleNamespace(from_weight=0.0, to_weight=0.005)
    construction = SimpleNamespace(
        target_cash_weight=0.795,
        blocks=(),
        expected_return_improvement=0.001,
        trades=(trade,),
    )
    optimizer = SimpleNamespace(deployable_cash_used=0.025)
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:partial",
        context=_context(),
        result=SimpleNamespace(
            decisions=(decision,),
            construction=construction,
            cycle_disposition=None,
        ),
        optimizer_proposal=optimizer,
    )
    assert accountability.positive_deployed_weight == 0.005
    assert accountability.optimized_deployable_weight == 0.025
    assert accountability.unfilled_optimized_weight == 0.02
    assert accountability.classification is ResidualCashClassification.UNEXPLAINED_RESIDUAL


def test_side_store_reloads_prior_signal_for_longitudinal_rotation(tmp_path):
    context = _context()
    store = SQLiteGlobalRotationStore(tmp_path / "rotation.sqlite")
    accountability = build_global_cash_accountability(
        cycle_identifier="cycle:one",
        context=context,
        result=SimpleNamespace(decisions=(), construction=None, cycle_disposition=None),
    )
    store.append(
        cycle_identifier="cycle:one",
        context=context,
        accountability=accountability,
        code_version="test",
    )
    snapshots = store.latest_signal_snapshots()
    assert snapshots["candidate:HBM"]["causal_stage"] == "accelerating_successor"
    assert snapshots["candidate:HBM"]["hierarchy_path"][-1] == "HBM"
    assert snapshots["candidate:HBM"]["longitudinal_state"] == "rotating_in"
    assert store.verify_integrity() is True
