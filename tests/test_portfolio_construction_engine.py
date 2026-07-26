"""Adversarial tests for cost-aware portfolio construction."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cio import CIOAction
from portfolio.construction_api import (
    ConstructionIntent,
    ConstructionStatus,
    ExposureLimit,
    PortfolioAsset,
    PortfolioConstructionEngine,
    PortfolioConstructionPolicy,
    PortfolioConstructionRequest,
    TradeSide,
)


AS_OF = datetime(2026, 7, 26, 17, tzinfo=timezone.utc)


def _policy(**overrides) -> PortfolioConstructionPolicy:
    values = {
        "version": "portfolio-construction.test.v1",
        "minimum_cash_weight": 0.02,
        "maximum_position_weight": 0.70,
        "default_maximum_sector_weight": 0.75,
        "default_maximum_correlation_bucket_weight": 0.75,
        "maximum_turnover": 0.30,
        "maximum_total_cost_return": 0.01,
        "minimum_replacement_edge": 0.01,
        "maximum_daily_volume_participation": 0.10,
        "execution_days": 3,
        "sector_limits": (),
        "factor_limits": (),
        "correlation_limits": (),
    }
    values.update(overrides)
    return PortfolioConstructionPolicy(**values)


def _asset(
    symbol: str,
    weight: float,
    *,
    expected_return: float = 0.07,
    sector: str = "Core",
    factor_loadings: tuple[tuple[str, float], ...] = (("market", 0.50),),
    bucket: str = "core",
    adv: float = 1_000_000_000.0,
    transaction_bps: float = 5.0,
    slippage_bps: float = 5.0,
    minimum_weight: float = 0.0,
    funding_eligible: bool = False,
) -> PortfolioAsset:
    return PortfolioAsset(
        symbol=symbol,
        current_weight=weight,
        expected_return=expected_return,
        sector=sector,
        factor_loadings=factor_loadings,
        correlation_bucket=bucket,
        average_daily_dollar_volume=adv,
        transaction_cost_bps=transaction_bps,
        slippage_bps=slippage_bps,
        minimum_weight=minimum_weight,
        funding_eligible=funding_eligible,
    )


def _intent(
    symbol: str,
    *,
    action: CIOAction = CIOAction.BUY,
    target: float | None = 0.08,
    expected_return: float = 0.15,
    opportunity_edge: float = 0.10,
    maximum_position_weight: float = 0.10,
    sector: str = "Health",
    factor_loadings: tuple[tuple[str, float], ...] = (("quality", 0.70),),
    bucket: str = "defensive",
    adv: float = 1_000_000_000.0,
    transaction_bps: float = 5.0,
    slippage_bps: float = 5.0,
    rank: int = 1,
) -> ConstructionIntent:
    return ConstructionIntent(
        candidate_identifier=f"candidate:{symbol.lower()}",
        symbol=symbol,
        action=action,
        requested_target_weight=target,
        expected_return=expected_return,
        opportunity_edge=opportunity_edge,
        maximum_position_weight=maximum_position_weight,
        sector=sector,
        factor_loadings=factor_loadings,
        correlation_bucket=bucket,
        average_daily_dollar_volume=adv,
        transaction_cost_bps=transaction_bps,
        slippage_bps=slippage_bps,
        priority_rank=rank,
    )


def _request(
    *,
    cash: float = 0.20,
    positions: tuple[PortfolioAsset, ...] | None = None,
    intents: tuple[ConstructionIntent, ...] = (),
    value: float = 10_000_000.0,
) -> PortfolioConstructionRequest:
    resolved_positions = positions or (
        _asset("CORE", 0.50, funding_eligible=True, minimum_weight=0.30),
        _asset(
            "TECH",
            0.30,
            expected_return=0.08,
            sector="Technology",
            factor_loadings=(("growth", 0.80),),
            bucket="growth",
            funding_eligible=True,
            minimum_weight=0.10,
        ),
    )
    assert sum(item.current_weight for item in resolved_positions) + cash == pytest.approx(1.0)
    return PortfolioConstructionRequest(
        identifier="construction:test",
        as_of=AS_OF,
        portfolio_value=value,
        cash_weight=cash,
        cash_expected_return=0.04,
        positions=resolved_positions,
        intents=intents,
    )


def _weights(result) -> dict[str, float]:
    return dict(result.target_weights)


def test_buy_uses_excess_cash_and_preserves_cash_floor() -> None:
    result = PortfolioConstructionEngine(_policy()).construct(
        _request(intents=(_intent("NEW"),))
    )

    assert result.status is ConstructionStatus.FEASIBLE
    assert _weights(result)["NEW"] == pytest.approx(0.08)
    assert result.target_cash_weight == pytest.approx(0.12)
    assert len(result.trades) == 1
    assert result.trades[0].side is TradeSide.BUY
    assert all(check.satisfied for check in result.constraints)


def test_explicit_low_return_holding_can_fund_superior_candidate() -> None:
    positions = (
        _asset(
            "CORE",
            0.57,
            expected_return=0.05,
            funding_eligible=True,
            minimum_weight=0.40,
        ),
        _asset(
            "TECH",
            0.40,
            expected_return=0.10,
            sector="Technology",
            factor_loadings=(("growth", 0.80),),
            bucket="growth",
            funding_eligible=False,
            minimum_weight=0.20,
        ),
    )
    result = PortfolioConstructionEngine(_policy()).construct(
        _request(cash=0.03, positions=positions, intents=(_intent("NEW"),))
    )

    weights = _weights(result)
    assert result.status is ConstructionStatus.FEASIBLE
    assert weights["NEW"] == pytest.approx(0.08)
    assert weights["CORE"] == pytest.approx(0.50)
    assert weights["TECH"] == pytest.approx(0.40)
    assert result.target_cash_weight == pytest.approx(0.02)
    core_sale = next(item for item in result.trades if item.symbol == "CORE")
    assert core_sale.side is TradeSide.SELL
    assert core_sale.funding_for == ("NEW",)


def test_funding_sale_is_rolled_back_when_candidate_is_infeasible() -> None:
    positions = (
        _asset(
            "CORE",
            0.57,
            expected_return=0.05,
            funding_eligible=True,
            minimum_weight=0.40,
        ),
        _asset(
            "TECH",
            0.40,
            expected_return=0.10,
            sector="Technology",
            factor_loadings=(("growth", 0.80),),
            bucket="growth",
            funding_eligible=False,
            minimum_weight=0.20,
        ),
    )
    policy = _policy(
        sector_limits=(ExposureLimit("Technology", 0.40),),
    )
    blocked = _intent("NEW", sector="Technology")

    result = PortfolioConstructionEngine(policy).construct(
        _request(cash=0.03, positions=positions, intents=(blocked,))
    )

    assert result.status is ConstructionStatus.BLOCKED
    assert result.trades == ()
    assert _weights(result) == {"CORE": pytest.approx(0.57), "TECH": pytest.approx(0.40)}
    assert result.target_cash_weight == pytest.approx(0.03)


def test_small_replacement_edge_does_not_sell_holding() -> None:
    positions = (
        _asset(
            "CORE",
            0.57,
            expected_return=0.05,
            funding_eligible=True,
            minimum_weight=0.40,
        ),
        _asset("TECH", 0.40, expected_return=0.10, funding_eligible=False),
    )
    intent = _intent("NEW", expected_return=0.055, opportunity_edge=0.005)

    result = PortfolioConstructionEngine(_policy()).construct(
        _request(cash=0.03, positions=positions, intents=(intent,))
    )

    assert result.status is ConstructionStatus.PARTIAL
    assert _weights(result)["NEW"] == pytest.approx(0.01, abs=1e-6)
    assert _weights(result)["CORE"] == pytest.approx(0.57)
    assert not any(item.side is TradeSide.SELL for item in result.trades)


def test_sector_limit_caps_allocation() -> None:
    policy = _policy(
        sector_limits=(ExposureLimit("Technology", 0.35),),
    )
    intent = _intent("NEW", sector="Technology")

    result = PortfolioConstructionEngine(policy).construct(
        _request(intents=(intent,))
    )

    assert result.status is ConstructionStatus.PARTIAL
    assert _weights(result)["NEW"] == pytest.approx(0.05, abs=1e-6)
    sector_check = next(
        item for item in result.constraints if item.name == "sector:Technology"
    )
    assert sector_check.satisfied
    assert sector_check.value == pytest.approx(0.35)


def test_factor_limit_caps_allocation() -> None:
    policy = _policy(
        factor_limits=(ExposureLimit("growth", 0.275),),
    )
    intent = _intent(
        "NEW",
        factor_loadings=(("growth", 0.70),),
    )

    result = PortfolioConstructionEngine(policy).construct(
        _request(intents=(intent,))
    )

    assert result.status is ConstructionStatus.PARTIAL
    assert _weights(result)["NEW"] == pytest.approx(0.05, abs=1e-6)
    factor_check = next(
        item for item in result.constraints if item.name == "factor:growth"
    )
    assert factor_check.satisfied
    assert factor_check.value == pytest.approx(0.275, abs=1e-6)


def test_correlation_limit_caps_allocation() -> None:
    policy = _policy(
        correlation_limits=(ExposureLimit("growth", 0.35),),
    )
    intent = _intent("NEW", bucket="growth")

    result = PortfolioConstructionEngine(policy).construct(
        _request(intents=(intent,))
    )

    assert result.status is ConstructionStatus.PARTIAL
    assert _weights(result)["NEW"] == pytest.approx(0.05, abs=1e-6)


def test_liquidity_limits_trade_size_using_portfolio_value() -> None:
    intent = _intent("NEW", adv=1_000_000.0)

    result = PortfolioConstructionEngine(_policy()).construct(
        _request(intents=(intent,), value=100_000_000.0)
    )

    assert result.status is ConstructionStatus.PARTIAL
    assert _weights(result)["NEW"] == pytest.approx(0.003, abs=1e-6)
    liquidity = next(
        item for item in result.constraints if item.name == "liquidity:NEW"
    )
    assert liquidity.limit == pytest.approx(0.003)


def test_turnover_limit_caps_allocation() -> None:
    result = PortfolioConstructionEngine(
        _policy(maximum_turnover=0.04)
    ).construct(_request(intents=(_intent("NEW"),)))

    assert result.status is ConstructionStatus.PARTIAL
    assert _weights(result)["NEW"] == pytest.approx(0.04, abs=1e-6)
    assert result.turnover == pytest.approx(0.04, abs=1e-6)


def test_cost_limit_caps_allocation() -> None:
    expensive = _intent(
        "NEW",
        transaction_bps=200.0,
        slippage_bps=200.0,
    )
    result = PortfolioConstructionEngine(
        _policy(maximum_total_cost_return=0.001)
    ).construct(_request(intents=(expensive,)))

    assert result.status is ConstructionStatus.PARTIAL
    assert _weights(result)["NEW"] == pytest.approx(0.025, abs=1e-6)
    assert result.estimated_cost_return == pytest.approx(0.001, abs=1e-6)


def test_exit_decision_frees_cash_without_execution() -> None:
    positions = (
        _asset("LEGACY", 0.10, expected_return=-0.08),
        _asset("CORE", 0.70, expected_return=0.07),
    )
    exit_intent = _intent(
        "LEGACY",
        action=CIOAction.EXIT,
        target=0.0,
        expected_return=-0.08,
        maximum_position_weight=0.10,
        sector="Legacy",
        bucket="legacy",
    )

    result = PortfolioConstructionEngine(_policy()).construct(
        _request(cash=0.20, positions=positions, intents=(exit_intent,))
    )

    assert result.status is ConstructionStatus.FEASIBLE
    assert "LEGACY" not in _weights(result)
    assert result.target_cash_weight == pytest.approx(0.30)
    assert result.trades[0].side is TradeSide.SELL
    assert not hasattr(PortfolioConstructionEngine, "execute")


def test_hold_and_abstention_intents_produce_no_trades() -> None:
    hold = _intent("CORE", action=CIOAction.HOLD, target=None)
    watch = _intent("WATCH", action=CIOAction.WATCH, target=None, rank=2)

    result = PortfolioConstructionEngine(_policy()).construct(
        _request(intents=(hold, watch))
    )

    assert result.status is ConstructionStatus.NO_ACTION
    assert result.trades == ()
    assert _weights(result) == {"CORE": pytest.approx(0.50), "TECH": pytest.approx(0.30)}


def test_priority_rank_allocates_scarce_cash_to_best_candidate_first() -> None:
    first = _intent("FIRST", rank=1)
    second = _intent("SECOND", rank=2)

    result = PortfolioConstructionEngine(_policy()).construct(
        _request(cash=0.10, positions=(
            _asset("CORE", 0.60),
            _asset("TECH", 0.30, sector="Technology", bucket="growth"),
        ), intents=(second, first))
    )

    weights = _weights(result)
    assert weights["FIRST"] == pytest.approx(0.08)
    assert "SECOND" not in weights
    assert result.status is ConstructionStatus.PARTIAL
    assert any("SECOND" in item for item in result.blocks)


def test_expected_return_improvement_is_net_of_costs() -> None:
    result = PortfolioConstructionEngine(_policy()).construct(
        _request(intents=(_intent("NEW"),))
    )

    assert result.estimated_cost_return > 0.0
    assert result.expected_return_after_cost == pytest.approx(
        result.expected_return_before + result.expected_return_improvement
    )
    assert result.expected_return_improvement > 0.0


def test_engine_source_does_not_use_cio_confidence_for_position_size() -> None:
    source = Path("portfolio/construction_engine.py").read_text(encoding="utf-8")

    assert "confidence" not in source
    assert "recommended_position_weight" not in source
    assert "requested_target_weight" in source


def test_result_is_a_proposal_and_contains_no_broker_execution_contract() -> None:
    result = PortfolioConstructionEngine(_policy()).construct(
        _request(intents=(_intent("NEW"),))
    )

    assert result.trades
    assert all(isinstance(item.reason, str) for item in result.trades)
    assert not hasattr(result, "order_ids")
    assert not hasattr(result, "fills")
    assert not hasattr(PortfolioConstructionEngine, "submit_orders")
