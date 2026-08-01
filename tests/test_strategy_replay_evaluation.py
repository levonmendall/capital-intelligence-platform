from __future__ import annotations

import pytest

from evaluation.strategy_replay import (
    CAPABILITY_AUTHORITY_REASON,
    StrategyReplayEvaluationError,
    evaluate_strategy_replay,
)


def _report(*observations):
    return {
        "schema_version": "canonical-historical-replay.v5",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "start_date": "2020-01-01",
        "end_date": "2022-01-01",
        "runtime_version": "test",
        "research_only": True,
        "execution_authorized": False,
        "paper_execution_authorized": False,
        "real_money_authorized": False,
        "policy_promotion_authorized": False,
        "performance_claims_authorized": False,
        "decision_cutoff_count": 2,
        "canonical_cio_invoked_count": 2,
        "blocked_cutoff_count": 0,
        "certification_ready": True,
        "initial_portfolio_value": 250000.0,
        "ending_portfolio_value": 250000.0,
        "ending_cash_weight": 1.0,
        "decisions": [
            {
                "cutoff": "2020-01-31T23:59:59Z",
                "state": "completed",
                "decisions": list(observations[:2]),
            },
            {
                "cutoff": "2021-01-31T23:59:59Z",
                "state": "completed",
                "decisions": list(observations[2:]),
            },
        ],
    }


def _observation(identifier, symbol, reasons, *, edge=0.05, realized=0.10):
    return {
        "identifier": identifier,
        "symbol": symbol,
        "asset_class": "crypto",
        "decision_stage": "pre_cio_qualification",
        "canonical_cio_decision": False,
        "universe_disposition": "intelligence_only",
        "qualification_outcome": "rejected",
        "qualification_reasons": list(reasons),
        "opportunity_edge": edge,
        "final_confidence": 0.70,
        "underlying_return_at_decision_horizon": realized,
        "effective_opportunity_cost": 0.02,
        "realized_outcome": "missed_opportunity" if realized > 0.02 else "avoided_loss",
    }


def test_evaluation_identifies_universal_pre_cio_capability_block():
    report = _report(
        _observation("a", "BTC-USD", (CAPABILITY_AUTHORITY_REASON,)),
        _observation(
            "b",
            "ETH-USD",
            (
                CAPABILITY_AUTHORITY_REASON,
                "expected downside exceeds the qualification limit",
            ),
            realized=-0.20,
        ),
        _observation("c", "BTC-USD", (CAPABILITY_AUTHORITY_REASON,)),
    )
    result = evaluate_strategy_replay(report, development_fraction=0.5)
    assert result["replay"]["observation_count"] == 3
    assert result["replay"]["canonical_cio_decision_observation_count"] == 0
    assert result["replay"]["universal_capability_authority_block"] is True
    assert result["ablation"]["capability_only_pass_count"] == 2
    assert result["strategy_go_no_go"]["portfolio_reset_authorized"] is False
    assert (
        result["strategy_go_no_go"]["verdict"]
        == "NO_GO_FOR_STRATEGY_CHANGE_RESET_OR_FORMAL_EXPERIMENT"
    )


def test_shadow_variants_are_chronologically_split_and_non_authoritative():
    report = _report(
        _observation("a", "BTC-USD", (CAPABILITY_AUTHORITY_REASON,), edge=0.04),
        _observation("b", "ETH-USD", (CAPABILITY_AUTHORITY_REASON,), edge=0.03),
        _observation("c", "SOL-USD", (CAPABILITY_AUTHORITY_REASON,), edge=0.06),
    )
    result = evaluate_strategy_replay(report, development_fraction=0.5)
    variants = result["shadow_variants"]["variants"]
    ranked = variants["capability_certified_continuous_ranking"]
    assert ranked["development"]["selected_cutoff_count"] == 1
    assert ranked["evaluation"]["selected_cutoff_count"] == 1
    assert ranked["development"]["maximum_position_weight"] == 0.01
    assert variants["reliability_weighted_specialist_evidence"]["status"] == "not_evaluable"
    assert result["authority"]["execution_authority_changed"] is False
    assert result["authority"]["performance_claims_authorized"] is False


def test_unsafe_replay_flags_fail_closed():
    report = _report(
        _observation("a", "BTC-USD", (CAPABILITY_AUTHORITY_REASON,)),
    )
    report["real_money_authorized"] = True
    with pytest.raises(StrategyReplayEvaluationError, match="real_money_authorized"):
        evaluate_strategy_replay(report)


def test_duplicate_observation_identifiers_are_rejected():
    item = _observation("same", "BTC-USD", (CAPABILITY_AUTHORITY_REASON,))
    report = _report(item, item)
    with pytest.raises(StrategyReplayEvaluationError, match="duplicate"):
        evaluate_strategy_replay(report)
