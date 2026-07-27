"""Tests for crypto, spot-FX, and global-equity construction boundaries."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cio import CIOAction, CandidateAssetClass
from governance import AssetClassApprovalState
from portfolio.construction_models import ConstructionIntent, PortfolioConstructionRequest
from portfolio.multi_asset_controls import (
    GovernedMultiAssetConstructionEngine,
    MultiAssetConstructionError,
    MultiAssetConstructionPolicy,
    MultiAssetInstrumentProfile,
)

AS_OF = datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc)


def _intent(symbol: str, weight: float) -> ConstructionIntent:
    return ConstructionIntent(
        candidate_identifier=f"candidate:{symbol}",
        symbol=symbol,
        action=CIOAction.BUY,
        requested_target_weight=weight,
        expected_return=0.15,
        opportunity_edge=0.05,
        maximum_position_weight=0.20,
        sector="expanded-market",
        factor_loadings=(),
        correlation_bucket="expanded-market",
        average_daily_dollar_volume=1_000_000_000,
        transaction_cost_bps=10,
        slippage_bps=10,
        priority_rank=1,
    )


def _request(symbol: str, weight: float) -> PortfolioConstructionRequest:
    return PortfolioConstructionRequest(
        identifier=f"construction:{symbol}",
        as_of=AS_OF,
        portfolio_value=100_000,
        cash_weight=1.0,
        cash_expected_return=0.04,
        positions=(),
        intents=(_intent(symbol, weight),),
    )


def _profile(
    symbol: str,
    asset_class: CandidateAssetClass,
    *,
    settlement_currency: str = "USD",
    state: AssetClassApprovalState = AssetClassApprovalState.PAPER_ELIGIBLE,
    unlevered: bool = True,
    spot_only: bool = True,
) -> MultiAssetInstrumentProfile:
    return MultiAssetInstrumentProfile(
        symbol=symbol,
        instrument_identifier=f"instrument:{symbol}",
        asset_class=asset_class,
        venue="COINBASE" if asset_class is CandidateAssetClass.CRYPTO else "EBS",
        country_code="GLOBAL",
        price_currency=settlement_currency,
        settlement_currency=settlement_currency,
        approval_identifier=f"approval:{asset_class.value}",
        approval_state=state,
        unlevered=unlevered,
        spot_only=spot_only,
        custody_settlement_identifier=f"custody:{asset_class.value}",
        execution_model_version=f"{asset_class.value}.paper-execution.v1",
    )


def test_crypto_construction_within_governed_limit_is_allowed() -> None:
    engine = GovernedMultiAssetConstructionEngine()
    profile = _profile("BTC-USD", CandidateAssetClass.CRYPTO)

    result = engine.construct(
        _request("BTC-USD", 0.04),
        profiles={"BTC-USD": profile},
        required_expanded_symbols=("BTC-USD",),
    )

    assert dict(result.target_weights)["BTC-USD"] == 0.04


def test_crypto_weight_above_asset_class_limit_fails_closed() -> None:
    profile = _profile("BTC-USD", CandidateAssetClass.CRYPTO)

    with pytest.raises(MultiAssetConstructionError, match="crypto target"):
        GovernedMultiAssetConstructionEngine().construct(
            _request("BTC-USD", 0.08),
            profiles={"BTC-USD": profile},
            required_expanded_symbols=("BTC-USD",),
        )


def test_fx_must_be_unlevered_spot_and_paper_eligible() -> None:
    with pytest.raises(MultiAssetConstructionError, match="unlevered spot"):
        GovernedMultiAssetConstructionEngine().construct(
            _request("EURUSD", 0.05),
            profiles={
                "EURUSD": _profile(
                    "EURUSD",
                    CandidateAssetClass.FX,
                    unlevered=False,
                )
            },
            required_expanded_symbols=("EURUSD",),
        )

    with pytest.raises(MultiAssetConstructionError, match="not paper_eligible"):
        GovernedMultiAssetConstructionEngine().construct(
            _request("EURUSD", 0.05),
            profiles={
                "EURUSD": _profile(
                    "EURUSD",
                    CandidateAssetClass.FX,
                    state=AssetClassApprovalState.RESEARCH_APPROVED,
                )
            },
            required_expanded_symbols=("EURUSD",),
        )


def test_expanded_profile_coverage_must_be_exact() -> None:
    with pytest.raises(MultiAssetConstructionError, match="exactly match"):
        GovernedMultiAssetConstructionEngine().construct(
            _request("BTC-USD", 0.04),
            profiles={},
            required_expanded_symbols=("BTC-USD",),
        )


def test_foreign_currency_limits_are_enforced() -> None:
    policy = MultiAssetConstructionPolicy(
        maximum_international_equity_weight=0.30,
        maximum_non_base_currency_weight=0.30,
        maximum_single_foreign_currency_weight=0.08,
    )
    engine = GovernedMultiAssetConstructionEngine(policy=policy)
    profile = _profile(
        "SHEL",
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        settlement_currency="GBP",
    )

    with pytest.raises(MultiAssetConstructionError, match="GBP target"):
        engine.construct(
            _request("SHEL", 0.12),
            profiles={"SHEL": profile},
            required_expanded_symbols=("SHEL",),
        )


def test_core_us_construction_remains_compatible_without_profiles() -> None:
    result = GovernedMultiAssetConstructionEngine().construct(
        _request("AAPL", 0.05),
        profiles={},
        required_expanded_symbols=(),
    )

    assert dict(result.target_weights)["AAPL"] == 0.05
