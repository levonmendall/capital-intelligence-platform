from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cio.cycle_disposition import (
    QualificationReasonCategory,
    classify_qualification_reason,
)
from portfolio.production_scenarios import (
    build_governed_portfolio_scenario_set,
)


def _candidate(
    symbol: str,
    *,
    bear_probability: float,
    base_probability: float,
    bull_probability: float,
):
    return SimpleNamespace(
        instrument=SimpleNamespace(symbol=symbol),
        bear_case_probability=bear_probability,
        base_case_probability=base_probability,
        bull_case_probability=bull_probability,
        bear_case_return=-0.20,
        base_case_return=0.08,
        bull_case_return=0.30,
        decision_horizon_days=365,
        evidence_identifiers=(f"evidence:{symbol}",),
        model_versions=("candidate-model.v1",),
    )


def test_unknown_qualification_reason_fails_closed():
    assert (
        classify_qualification_reason("new unmapped provider condition")
        is QualificationReasonCategory.UNCLASSIFIED
    )


def test_known_economic_reason_is_typed():
    assert (
        classify_qualification_reason(
            "horizon-normalized opportunity edge is below the full-conviction margin"
        )
        is QualificationReasonCategory.ECONOMIC_RETURN
    )


def test_joint_scenarios_preserve_common_and_idiosyncratic_states():
    as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)
    values = build_governed_portfolio_scenario_set(
        identifier="scenario:test",
        source_identifier="publication:test",
        as_of=as_of,
        knowledge_cutoff=as_of - timedelta(minutes=1),
        candidates=(
            _candidate(
                "AAA",
                bear_probability=0.30,
                base_probability=0.50,
                bull_probability=0.20,
            ),
            _candidate(
                "BBB",
                bear_probability=0.15,
                base_probability=0.60,
                bull_probability=0.25,
            ),
        ),
        cash_expected_return=0.04,
    )

    assert {item.name for item in values.scenarios}.issuperset(
        {
            "common_bear",
            "common_base",
            "common_bull",
            "idiosyncratic_bear:AAA",
            "idiosyncratic_bear:BBB",
        }
    )
    assert abs(sum(item.probability for item in values.scenarios) - 1.0) < 0.000001
    assert all(item.symbols == frozenset({"AAA", "BBB"}) for item in values.scenarios)
    assert "production-joint-scenario-normalization.v2" in values.model_versions
