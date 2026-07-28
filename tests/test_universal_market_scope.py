"""Universal-market scope, governance, and contract-accounting regression tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass, CandidateInstrument
from cio.universe import RecommendationUniversePolicy, UniverseDisposition
from governance import (
    CORE_POLICY_ASSET_CLASSES,
    UNIVERSAL_GOVERNED_ASSET_CLASSES,
    AssetClassApproval,
    AssetClassApprovalState,
    AssetClassCapabilityProfile,
    AssetClassScopeAuthority,
    CustodySettlementModel,
    SQLiteAssetClassApprovalStore,
    TradingSessionModel,
)
from portfolio.multi_asset_controls import MultiAssetConstructionPolicy
from portfolio.multi_asset_execution import MultiAssetExecutionPolicy
from portfolio.state import CanonicalPortfolioPosition, position_to_dict, snapshot_from_dict, snapshot_to_dict, CanonicalPortfolioSnapshot
from run_asset_class_governance import _status_payload

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 20, 0, tzinfo=UTC)

_CONFIG = {
    CandidateAssetClass.INTERNATIONAL_EQUITY: ("LSE", "GB", "common_stock", TradingSessionModel.EXCHANGE_LOCAL, CustodySettlementModel.BROKER_CUSTODIED_SECURITY),
    CandidateAssetClass.FIXED_INCOME: ("TRACE", "US", "bond", TradingSessionModel.DEALER_24_5, CustodySettlementModel.CENTRAL_SECURITIES_DEPOSITORY),
    CandidateAssetClass.COMMODITY: ("CME", "US", "future", TradingSessionModel.EXCHANGE_LOCAL, CustodySettlementModel.FUTURES_CLEARING),
    CandidateAssetClass.FX: ("EBS", "GLOBAL", "spot", TradingSessionModel.CONTINUOUS_24_5, CustodySettlementModel.PRIME_BROKER_SPOT_FX),
    CandidateAssetClass.CRYPTO: ("COINBASE", "GLOBAL", "token", TradingSessionModel.CONTINUOUS_24_7, CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY),
    CandidateAssetClass.REAL_ESTATE: ("NYSE", "US", "common_stock", TradingSessionModel.EXCHANGE_LOCAL, CustodySettlementModel.BROKER_CUSTODIED_SECURITY),
    CandidateAssetClass.FUTURE: ("CME", "US", "future", TradingSessionModel.EXCHANGE_LOCAL, CustodySettlementModel.FUTURES_CLEARING),
    CandidateAssetClass.OPTION: ("CBOE", "US", "option", TradingSessionModel.EXCHANGE_LOCAL, CustodySettlementModel.OPTIONS_CLEARING),
    CandidateAssetClass.VOLATILITY: ("CFE", "US", "future", TradingSessionModel.EXCHANGE_LOCAL, CustodySettlementModel.FUTURES_CLEARING),
    CandidateAssetClass.ALTERNATIVE: ("NYSEARCA", "US", "fund", TradingSessionModel.EXCHANGE_LOCAL, CustodySettlementModel.BROKER_CUSTODIED_SECURITY),
}


def _candidate(asset_class: CandidateAssetClass) -> CandidateInstrument:
    venue, country, instrument_type, _, _ = _CONFIG[asset_class]
    return CandidateInstrument(
        instrument_id=f"instrument:{asset_class.value}:test",
        symbol=f"{asset_class.value[:6].upper()}1",
        name=f"Test {asset_class.value}",
        asset_class=asset_class,
        venue=venue,
        country_code=country,
        average_daily_dollar_volume=250_000_000,
        data_age_hours=1,
        analytical_coverage=0.95,
        security_master_snapshot_identifier="security-master:universal",
        security_master_record_identifiers=("record:universal",),
        instrument_type=instrument_type,
        uses_derivatives=instrument_type in {"future", "option", "perpetual"},
    )


def _profile(asset_class: CandidateAssetClass) -> AssetClassCapabilityProfile:
    venue, country, instrument_type, session, custody = _CONFIG[asset_class]
    derivative = instrument_type in {"future", "option", "perpetual"}
    return AssetClassCapabilityProfile(
        asset_class=asset_class,
        state=AssetClassApprovalState.PAPER_ELIGIBLE,
        approved_venues=(venue,),
        approved_country_codes=(country,),
        base_currency="USD",
        supported_quote_currencies=("USD",),
        trading_session_model=session,
        custody_settlement_model=custody,
        allowed_instrument_types=(instrument_type,),
        maximum_gross_leverage=1.0,
        identity_model_version="identity.v1",
        valuation_model_version="valuation.v1",
        expected_return_model_version="expected-return.v1",
        liquidity_model_version="liquidity.v1",
        cost_model_version="cost.v1",
        portfolio_risk_model_version="risk.v1",
        execution_model_version="execution.v1",
        thesis_model_version="thesis.v1",
        evaluation_model_version="evaluation.v1",
        contract_model_version="contract.v1" if derivative else None,
        margin_model_version="margin.v1" if derivative else None,
        lifecycle_model_version="lifecycle.v1" if derivative else None,
        roll_model_version=(
            "roll.v1"
            if instrument_type in {"future", "perpetual"}
            else None
        ),
        security_master_certification_identifier="cert:security-master",
        market_data_certification_identifier="cert:market-data",
        analytical_evidence_certification_identifier="cert:evidence",
        execution_certification_identifier="cert:execution",
        custody_settlement_identifier="cert:custody",
        source_identifiers=("source:universal",),
        limitations=("paper-only",),
    )


def _append(store: SQLiteAssetClassApprovalStore, asset_class: CandidateAssetClass) -> None:
    store.append(
        AssetClassApproval(
            identifier=f"approval:{asset_class.value}:universal-v1",
            profile=_profile(asset_class),
            approved_at=AS_OF - timedelta(days=2),
            effective_at=AS_OF - timedelta(days=1),
            expires_at=AS_OF + timedelta(days=30),
            governance_identifier="governance:universal-markets",
            process_version="capital-intelligence-investment-process.development",
            code_version="commit:test",
            rationale="Complete paper capability approved for universal scope.",
        )
    )


def test_universal_governed_scope_covers_every_classified_non_core_market() -> None:
    assert UNIVERSAL_GOVERNED_ASSET_CLASSES == (
        set(CandidateAssetClass)
        - set(CORE_POLICY_ASSET_CLASSES)
        - {CandidateAssetClass.OTHER}
    )
    assert set(_CONFIG) == set(UNIVERSAL_GOVERNED_ASSET_CLASSES)


@pytest.mark.parametrize("asset_class", tuple(_CONFIG))
def test_every_governed_market_can_enter_direct_recommendation_after_complete_approval(
    tmp_path: Path,
    asset_class: CandidateAssetClass,
) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / f"{asset_class.value}.db")
    _append(store, asset_class)
    assessment = RecommendationUniversePolicy(
        asset_class_authority=AssetClassScopeAuthority(store)
    ).evaluate(_candidate(asset_class), as_of=AS_OF)

    assert assessment.disposition is UniverseDisposition.DIRECT_RECOMMENDATION
    assert assessment.asset_class_approval_identifier == (
        f"approval:{asset_class.value}:universal-v1"
    )


@pytest.mark.parametrize("asset_class", tuple(_CONFIG))
def test_every_governed_market_remains_evidence_only_without_active_approval(
    tmp_path: Path,
    asset_class: CandidateAssetClass,
) -> None:
    assessment = RecommendationUniversePolicy(
        asset_class_authority=AssetClassScopeAuthority(
            SQLiteAssetClassApprovalStore(tmp_path / f"missing-{asset_class.value}.db")
        )
    ).evaluate(_candidate(asset_class), as_of=AS_OF)

    assert assessment.disposition is UniverseDisposition.INTELLIGENCE_ONLY
    assert "no active asset-class governance approval" in assessment.reasons[0]


def test_us_listed_wrapper_is_governed_by_underlying_crypto_exposure(tmp_path: Path) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / "wrapper.db")
    _append(store, CandidateAssetClass.CRYPTO)
    profile = _profile(CandidateAssetClass.CRYPTO)
    profile = AssetClassCapabilityProfile.from_dict(
        {
            **profile.to_dict(),
            "approved_venues": ["NYSEARCA"],
            "approved_country_codes": ["US"],
            "allowed_instrument_types": ["fund"],
            "trading_session_model": "exchange_local",
            "custody_settlement_model": "broker_custodied_security",
        }
    )
    store.append(
        AssetClassApproval(
            identifier="approval:crypto:listed-wrapper",
            profile=profile,
            approved_at=AS_OF - timedelta(days=2),
            effective_at=AS_OF - timedelta(days=1),
            expires_at=AS_OF + timedelta(days=30),
            governance_identifier="governance:crypto-wrapper",
            process_version="process:v1",
            code_version="commit:test",
            rationale="Crypto economic exposure through a listed fund.",
        )
    )
    instrument = CandidateInstrument(
        instrument_id="instrument:spot-bitcoin-etf",
        symbol="BTCF",
        name="Spot Bitcoin Fund",
        asset_class=CandidateAssetClass.US_ETF,
        economic_exposure_class=CandidateAssetClass.CRYPTO,
        instrument_type="fund",
        venue="NYSEARCA",
        country_code="US",
        average_daily_dollar_volume=100_000_000,
        data_age_hours=1,
        analytical_coverage=0.95,
        security_master_snapshot_identifier="security-master:wrapper",
        security_master_record_identifiers=("record:wrapper",),
    )

    assessment = RecommendationUniversePolicy(
        asset_class_authority=AssetClassScopeAuthority(store)
    ).evaluate(instrument, as_of=AS_OF)

    assert assessment.disposition is UniverseDisposition.DIRECT_RECOMMENDATION
    assert assessment.asset_class_approval_identifier == "approval:crypto:listed-wrapper"

    direct = RecommendationUniversePolicy(
        asset_class_authority=AssetClassScopeAuthority(store)
    ).evaluate(_candidate(CandidateAssetClass.CRYPTO), as_of=AS_OF)
    assert direct.disposition is UniverseDisposition.DIRECT_RECOMMENDATION
    assert direct.asset_class_approval_identifier == "approval:crypto:universal-v1"



def test_governance_status_reports_all_active_structure_specific_profiles(
    tmp_path: Path,
) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / "status.db")
    _append(store, CandidateAssetClass.CRYPTO)
    listed_profile = AssetClassCapabilityProfile.from_dict(
        {
            **_profile(CandidateAssetClass.CRYPTO).to_dict(),
            "approved_venues": ["NYSEARCA"],
            "approved_country_codes": ["US"],
            "allowed_instrument_types": ["fund"],
            "trading_session_model": "exchange_local",
            "custody_settlement_model": "broker_custodied_security",
        }
    )
    store.append(
        AssetClassApproval(
            identifier="approval:crypto:fund-status",
            profile=listed_profile,
            approved_at=AS_OF - timedelta(days=2),
            effective_at=AS_OF - timedelta(days=1),
            expires_at=AS_OF + timedelta(days=30),
            governance_identifier="governance:crypto-fund-status",
            process_version="process:v1",
            code_version="commit:test",
            rationale="Listed crypto exposure profile.",
        )
    )

    payload = _status_payload(store, evaluated_at=AS_OF)
    crypto = next(
        item for item in payload["markets"] if item["asset_class"] == "crypto"
    )

    assert crypto["paper_eligible"] is True
    assert crypto["active_approval_identifiers"] == [
        "approval:crypto:universal-v1",
        "approval:crypto:fund-status",
    ]
    assert {
        tuple(item["allowed_instrument_types"])
        for item in crypto["active_capability_profiles"]
    } == {("token",), ("fund",)}

def test_contract_multiplier_is_preserved_in_canonical_valuation_round_trip() -> None:
    position = CanonicalPortfolioPosition(
        symbol="ESZ6",
        quantity=2,
        average_cost=5_000,
        mark_price=5_100,
        updated_at=AS_OF,
        instrument_identifier="future:CME:ESZ6",
        venue="CME",
        asset_class=CandidateAssetClass.FUTURE.value,
        contract_multiplier=50,
    )
    snapshot = CanonicalPortfolioSnapshot(
        identifier="portfolio:contract-multiplier",
        portfolio_code="COMPOUNDING",
        display_name="Capital Intelligence Portfolio",
        constraint_profile="test",
        as_of=AS_OF,
        starting_capital=250_000,
        cash_amount=10_000,
        positions=(position,),
    )

    assert position.local_cost_basis == 500_000
    assert position.local_market_value == 510_000
    restored = snapshot_from_dict(snapshot_to_dict(snapshot))
    assert restored.positions[0].contract_multiplier == 50
    assert position_to_dict(restored.positions[0])["contract_multiplier"] == 50


def test_universal_execution_policy_has_asset_specific_routes_and_limits() -> None:
    construction = MultiAssetConstructionPolicy()
    execution = MultiAssetExecutionPolicy()
    for asset_class in UNIVERSAL_GOVERNED_ASSET_CLASSES:
        assert 0 < construction.class_limit(asset_class) <= 1
        assert execution.commission_bps(asset_class) >= 0
        assert isinstance(execution.session_model(asset_class), TradingSessionModel)
