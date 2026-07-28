"""Fail-closed tests for universal liquid-market capability governance."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass, CandidateInstrument
from cio.universe import RecommendationUniversePolicy, UniverseDisposition
from governance import (
    AssetClassApproval,
    AssetClassApprovalState,
    AssetClassCapabilityProfile,
    AssetClassScopeAuthority,
    CustodySettlementModel,
    SQLiteAssetClassApprovalStore,
    TradingSessionModel,
)

UTC = timezone.utc
DECISION_TIME = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _candidate(
    asset_class: CandidateAssetClass,
    *,
    venue: str,
    country_code: str,
    symbol: str,
) -> CandidateInstrument:
    return CandidateInstrument(
        instrument_id=f"instrument:{asset_class.value}:{venue}:{symbol}",
        symbol=symbol,
        name=f"Test {symbol}",
        asset_class=asset_class,
        venue=venue,
        country_code=country_code,
        average_daily_dollar_volume=250_000_000,
        data_age_hours=1,
        analytical_coverage=0.95,
        security_master_snapshot_identifier="security-master:test",
        security_master_record_identifiers=("record:test",),
        instrument_type={
            CandidateAssetClass.CRYPTO: "token",
            CandidateAssetClass.FX: "spot",
            CandidateAssetClass.INTERNATIONAL_EQUITY: "common_stock",
        }.get(asset_class, "other"),
    )


def _complete_profile(
    asset_class: CandidateAssetClass,
    *,
    state: AssetClassApprovalState = AssetClassApprovalState.PAPER_ELIGIBLE,
) -> AssetClassCapabilityProfile:
    if asset_class is CandidateAssetClass.CRYPTO:
        venue = "COINBASE"
        countries = ("GLOBAL",)
        session = TradingSessionModel.CONTINUOUS_24_7
        custody = CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY
    elif asset_class is CandidateAssetClass.FX:
        venue = "EBS"
        countries = ("GLOBAL",)
        session = TradingSessionModel.CONTINUOUS_24_5
        custody = CustodySettlementModel.PRIME_BROKER_SPOT_FX
    elif asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        venue = "LSE"
        countries = ("GB",)
        session = TradingSessionModel.EXCHANGE_LOCAL
        custody = CustodySettlementModel.BROKER_CUSTODIED_SECURITY
    else:
        raise AssertionError("unsupported test asset class")
    complete = state is AssetClassApprovalState.PAPER_ELIGIBLE
    value = "v1" if complete else None
    identifier = "certification:test" if complete else None
    return AssetClassCapabilityProfile(
        asset_class=asset_class,
        state=state,
        approved_venues=(venue,),
        approved_country_codes=countries,
        base_currency="USD",
        supported_quote_currencies=("USD",),
        trading_session_model=session,
        custody_settlement_model=custody,
        identity_model_version=value,
        valuation_model_version=value,
        expected_return_model_version=value,
        liquidity_model_version=value,
        cost_model_version=value,
        portfolio_risk_model_version=value,
        execution_model_version=value,
        thesis_model_version=value,
        evaluation_model_version=value,
        security_master_certification_identifier=identifier,
        market_data_certification_identifier=identifier,
        analytical_evidence_certification_identifier=identifier,
        execution_certification_identifier=identifier,
        custody_settlement_identifier=identifier,
        source_identifiers=("source:test",) if complete else (),
        limitations=("paper-only",),
    )


def _approval(
    profile: AssetClassCapabilityProfile,
    *,
    identifier: str | None = None,
    effective_at: datetime = DECISION_TIME - timedelta(days=1),
    expires_at: datetime = DECISION_TIME + timedelta(days=30),
) -> AssetClassApproval:
    return AssetClassApproval(
        identifier=identifier or f"approval:{profile.asset_class.value}:{profile.state.value}",
        profile=profile,
        approved_at=effective_at - timedelta(hours=1),
        effective_at=effective_at,
        expires_at=expires_at,
        governance_identifier="governance:multi-asset-review",
        process_version="capital-intelligence-investment-process.development",
        code_version="commit:test",
        rationale="Controlled paper-market capability review.",
    )


@pytest.mark.parametrize(
    ("asset_class", "venue", "country", "symbol"),
    (
        (CandidateAssetClass.CRYPTO, "COINBASE", "GLOBAL", "BTC-USD"),
        (CandidateAssetClass.FX, "EBS", "GLOBAL", "EURUSD"),
        (CandidateAssetClass.INTERNATIONAL_EQUITY, "LSE", "GB", "SHEL"),
    ),
)
def test_expansion_markets_remain_intelligence_only_without_approval(
    tmp_path: Path,
    asset_class: CandidateAssetClass,
    venue: str,
    country: str,
    symbol: str,
) -> None:
    authority = AssetClassScopeAuthority(
        SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    )
    policy = RecommendationUniversePolicy(asset_class_authority=authority)

    assessment = policy.evaluate(
        _candidate(
            asset_class,
            venue=venue,
            country_code=country,
            symbol=symbol,
        ),
        as_of=DECISION_TIME,
    )

    assert assessment.disposition is UniverseDisposition.INTELLIGENCE_ONLY
    assert assessment.asset_class_approval_identifier is None
    assert "no active asset-class governance approval" in assessment.reasons[0]


@pytest.mark.parametrize(
    ("asset_class", "venue", "country", "symbol"),
    (
        (CandidateAssetClass.CRYPTO, "COINBASE", "GLOBAL", "BTC-USD"),
        (CandidateAssetClass.FX, "EBS", "GLOBAL", "EURUSD"),
        (CandidateAssetClass.INTERNATIONAL_EQUITY, "LSE", "GB", "SHEL"),
    ),
)
def test_complete_active_approval_allows_paper_recommendation_scope(
    tmp_path: Path,
    asset_class: CandidateAssetClass,
    venue: str,
    country: str,
    symbol: str,
) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    approval = _approval(_complete_profile(asset_class))
    store.append(approval)
    policy = RecommendationUniversePolicy(
        asset_class_authority=AssetClassScopeAuthority(store)
    )

    assessment = policy.evaluate(
        _candidate(
            asset_class,
            venue=venue,
            country_code=country,
            symbol=symbol,
        ),
        as_of=DECISION_TIME,
    )

    assert assessment.disposition is UniverseDisposition.DIRECT_RECOMMENDATION
    assert assessment.asset_class_approval_identifier == approval.identifier
    assert assessment.asset_class_approval_state is AssetClassApprovalState.PAPER_ELIGIBLE
    assert assessment.asset_class_policy_version == "universal-market-scope-governance.v1"


def test_research_approval_cannot_authorize_portfolio_action(tmp_path: Path) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    approval = _approval(
        _complete_profile(
            CandidateAssetClass.CRYPTO,
            state=AssetClassApprovalState.RESEARCH_APPROVED,
        )
    )
    store.append(approval)
    policy = RecommendationUniversePolicy(
        asset_class_authority=AssetClassScopeAuthority(store)
    )

    assessment = policy.evaluate(
        _candidate(
            CandidateAssetClass.CRYPTO,
            venue="COINBASE",
            country_code="GLOBAL",
            symbol="BTC-USD",
        ),
        as_of=DECISION_TIME,
    )

    assert assessment.disposition is UniverseDisposition.INTELLIGENCE_ONLY
    assert assessment.asset_class_approval_identifier == approval.identifier
    assert "not paper_eligible" in assessment.reasons[0]


def test_paper_approval_requires_every_asset_specific_capability() -> None:
    with pytest.raises(ValueError, match="paper-eligible asset-class profile is incomplete"):
        AssetClassCapabilityProfile(
            asset_class=CandidateAssetClass.FX,
            state=AssetClassApprovalState.PAPER_ELIGIBLE,
            approved_venues=("EBS",),
            approved_country_codes=("GLOBAL",),
            base_currency="USD",
            supported_quote_currencies=("USD",),
            trading_session_model=TradingSessionModel.CONTINUOUS_24_5,
            custody_settlement_model=CustodySettlementModel.PRIME_BROKER_SPOT_FX,
        )


def test_asset_specific_session_and_custody_models_are_enforced() -> None:
    with pytest.raises(ValueError, match="continuous 24/7"):
        AssetClassCapabilityProfile(
            asset_class=CandidateAssetClass.CRYPTO,
            state=AssetClassApprovalState.EVIDENCE_ONLY,
            approved_venues=(),
            approved_country_codes=(),
            base_currency="USD",
            supported_quote_currencies=(),
            trading_session_model=TradingSessionModel.EXCHANGE_LOCAL,
            custody_settlement_model=(
                CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY
            ),
        )


def test_expired_or_wrong_venue_approval_fails_closed(tmp_path: Path) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    store.append(
        _approval(
            _complete_profile(CandidateAssetClass.CRYPTO),
            expires_at=DECISION_TIME - timedelta(seconds=1),
        )
    )
    authority = AssetClassScopeAuthority(store)
    candidate = _candidate(
        CandidateAssetClass.CRYPTO,
        venue="KRAKEN",
        country_code="GLOBAL",
        symbol="BTC-USD",
    )

    expired = authority.assess(candidate, evaluated_at=DECISION_TIME)
    assert expired.direct_recommendation_allowed is False
    assert expired.approval_identifier is None

    active = _approval(
        _complete_profile(CandidateAssetClass.CRYPTO),
        identifier="approval:crypto:replacement",
        effective_at=DECISION_TIME,
    )
    store.append(active)
    wrong_venue = authority.assess(
        candidate,
        evaluated_at=DECISION_TIME + timedelta(seconds=1),
    )
    assert wrong_venue.direct_recommendation_allowed is False
    assert wrong_venue.approval_identifier == active.identifier
    assert "outside the asset-class approval" in wrong_venue.reasons[0]


def test_suspension_supersedes_prior_paper_approval(tmp_path: Path) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    store.append(_approval(_complete_profile(CandidateAssetClass.FX)))
    suspension = _approval(
        _complete_profile(
            CandidateAssetClass.FX,
            state=AssetClassApprovalState.SUSPENDED,
        ),
        identifier="approval:fx:suspended",
        effective_at=DECISION_TIME - timedelta(minutes=1),
    )
    store.append(suspension)
    authority = AssetClassScopeAuthority(store)

    assessment = authority.assess(
        _candidate(
            CandidateAssetClass.FX,
            venue="EBS",
            country_code="GLOBAL",
            symbol="EURUSD",
        ),
        evaluated_at=DECISION_TIME,
    )

    assert assessment.direct_recommendation_allowed is False
    assert assessment.approval_identifier == suspension.identifier
    assert assessment.approval_state is AssetClassApprovalState.SUSPENDED


def test_core_us_universe_behavior_does_not_require_expansion_approval() -> None:
    candidate = _candidate(
        CandidateAssetClass.US_EQUITY,
        venue="NASDAQ",
        country_code="US",
        symbol="AAPL",
    )

    assessment = RecommendationUniversePolicy().evaluate(candidate)

    assert assessment.disposition is UniverseDisposition.DIRECT_RECOMMENDATION
    assert assessment.asset_class_approval_identifier is None


def test_asset_class_approval_history_is_append_only(tmp_path: Path) -> None:
    store = SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    approval = _approval(_complete_profile(CandidateAssetClass.INTERNATIONAL_EQUITY))
    assert store.append(approval) == 1
    assert store.append(approval) == 1
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE asset_class_approvals SET payload_json = '{}' WHERE sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM asset_class_approvals")
