from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cio import HistoricalLearningResolver
from historical_replay.canonical_runtime_v4 import (
    HorizonAlignedCanonicalHistoricalReplayEngine,
)
from tests.test_canonical_no_action_learning import _live_candidate

UTC = timezone.utc


def test_live_calibration_bounds_extreme_regret_but_preserves_raw_value() -> None:
    report = {
        "schema_version": "canonical-historical-replay.v4",
        "runtime_version": "single-pass-availability-cursor.v4",
        "generated_at": "2026-07-29T00:00:00Z",
        "strict_only": True,
        "governance_only_observation_count": 1,
        "decisions": [
            {
                "state": "completed",
                "decisions": [
                    {
                        "candidate_identifier": "governance-only",
                        "calibration_eligible": False,
                        "realized_decision_value_at_horizon": -0.25,
                    },
                    {
                        "candidate_identifier": "eligible",
                        "calibration_eligible": True,
                        "realized_decision_value_at_horizon": -1.20,
                    },
                ],
            }
        ],
    }

    learning = HorizonAlignedCanonicalHistoricalReplayEngine._learning_input_report(
        report
    )

    assert learning["learning_observation_count"] == 1
    assert learning["governance_only_observation_count"] == 1
    assert learning["bounded_calibration_outcome_count"] == 1
    observation = learning["decisions"][0]["decisions"][0]
    assert observation["realized_decision_value_at_horizon"] == pytest.approx(-1.20)
    assert observation["calibration_return_at_horizon"] == pytest.approx(-1.0)
    assert observation["calibration_return_was_bounded"] is True
    assert observation["realized_return_to_next_cutoff"] == pytest.approx(-1.0)


def test_live_resolver_discloses_bounded_regret_and_policy_exclusions(tmp_path) -> None:
    generated_at = datetime(2026, 7, 29, 12, tzinfo=UTC)
    payload = {
        "schema_version": "canonical-historical-learning-input.v1",
        "generated_at": generated_at.isoformat(),
        "strict_only": True,
        "outcome_alignment": "decision_horizon",
        "governance_only_observation_count": 4,
        "bounded_calibration_outcome_count": 2,
        "decisions": [
            {
                "state": "completed",
                "macro_regime": "risk_on",
                "decisions": [
                    {
                        "candidate_identifier": "historical:btc",
                        "symbol": "BTC-USD",
                        "asset_class": "crypto",
                        "decision_horizon_days": 365,
                        "macro_regime": "risk_on",
                        "market_regime": "positive_trend",
                        "action": "no_superior_opportunity",
                        "final_confidence": 0.60,
                        "recommended_position_weight": None,
                        "realized_return_to_next_cutoff": -1.0,
                    }
                ],
            }
        ],
    }
    path = tmp_path / "latest-canonical-learning.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    as_of = generated_at + timedelta(seconds=1)

    context = HistoricalLearningResolver(
        path,
        minimum_sample_size=1,
    ).resolve(
        _live_candidate(as_of),
        as_of=as_of,
        macro_regime="risk_on",
        market_regime="positive_trend",
    )

    assert "4 capability-policy-only" in context.summary
    assert "2 extreme decision-relative regret" in context.summary
    assert any("bounded at -100%" in item for item in context.limitations)
    assert any("governance-only-excluded:4" in item for item in context.evidence_identifiers)
    assert any("bounded-calibration-outcomes:2" in item for item in context.evidence_identifiers)
    assert context.execution_authorized is False
    assert context.policy_promotion_authorized is False
