"""Point-in-time tests for the governed multi-asset universe builder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cio import CandidateAssetClass
from cio.universe import RecommendationUniversePolicy
from data import (
    AssetClass,
    Instrument,
    InstrumentRecord,
    InstrumentType,
    ListingRecord,
    ListingStatus,
    MultiAssetUniverseBuilder,
    PointInTimeSecurityMasterSnapshot,
    SecurityMasterCoverage,
    SecurityMasterMarketMetrics,
    TradingCalendar,
)
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
AS_OF = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _coverage() -> SecurityMasterCoverage:
    return SecurityMasterCoverage(
        source="LICENSED_MULTI_ASSET_FIXTURE",
        source_version="fixture.v1",
        licensed=True,
        complete_universe=True,
        point_in_time=True,
        historical_identifiers=True,
        listing_history=True,
        delistings=True,
        corporate_actions=True,
        provenance_complete=True,
        service_level_defined=True,
    )


def _instrument_record(instrument: Instrument) -> InstrumentRecord:
    return InstrumentRecord(
        record_identifier=f"record:{instrument.instrument_id}",
        instrument=instrument,
        effective_from=AS_OF - timedelta(days=365),
        effective_until=None,
        available_at=AS_OF,
        source_identifier=f"source:{instrument.instrument_id}",
    )


def _listing(
    instrument: Instrument,
    *,
    venue: str,
    symbol: str,
    country: str,
    calendar: TradingCalendar,
) -> ListingRecord:
    return ListingRecord(
        record_identifier=f"record:listing:{venue}:{symbol}",
        listing_identifier=f"listing:{venue}:{symbol}",
        instrument_identifier=instrument.instrument_id,
        venue=venue,
        symbol=symbol,
        country_code=country,
        trading_calendar=calendar,
        status=ListingStatus.ACTIVE,
        primary=True,
        effective_from=AS_OF - timedelta(days=365),
        effective_until=None,
        available_at=AS_OF,
        source_identifier=f"source:listing:{venue}:{symbol}",
    )


def _metric(instrument: Instrument) -> SecurityMasterMarketMetrics:
    return SecurityMasterMarketMetrics(
        identifier=f"metric:{instrument.instrument_id}",
        instrument_identifier=instrument.instrument_id,
        observed_at=AS_OF,
        available_at=AS_OF,
        average_daily_dollar_volume=500_000_000,
        analytical_coverage=0.95,
    )


def _profile(asset_class: CandidateAssetClass) -> AssetClassCapabilityProfile:
    if asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        venues = ("LSE",)
        countries = ("GB",)
        session = TradingSessionModel.EXCHANGE_LOCAL
        custody = CustodySettlementModel.BROKER_CUSTODIED_SECURITY
    elif asset_class is CandidateAssetClass.FX:
        venues = ("EBS",)
        countries = ("GLOBAL",)
        session = TradingSessionModel.CONTINUOUS_24_5
        custody = CustodySettlementModel.PRIME_BROKER_SPOT_FX
    elif asset_class is CandidateAssetClass.CRYPTO:
        venues = ("COINBASE",)
        countries = ("GLOBAL",)
        session = TradingSessionModel.CONTINUOUS_24_7
        custody = CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY
    else:
        raise AssertionError("unsupported profile")
    return AssetClassCapabilityProfile(
        asset_class=asset_class,
        state=AssetClassApprovalState.PAPER_ELIGIBLE,
        approved_venues=venues,
        approved_country_codes=countries,
        base_currency="USD",
        supported_quote_currencies=("USD",),
        trading_session_model=session,
        custody_settlement_model=custody,
        identity_model_version=f"{asset_class.value}.identity.v1",
        valuation_model_version=f"{asset_class.value}.valuation.v1",
        expected_return_model_version=f"{asset_class.value}.returns.v1",
        liquidity_model_version=f"{asset_class.value}.liquidity.v1",
        cost_model_version=f"{asset_class.value}.costs.v1",
        portfolio_risk_model_version=f"{asset_class.value}.risk.v1",
        execution_model_version=f"{asset_class.value}.paper-execution.v1",
        thesis_model_version=f"{asset_class.value}.thesis.v1",
        evaluation_model_version=f"{asset_class.value}.evaluation.v1",
        security_master_certification_identifier=f"cert:{asset_class.value}:identity",
        market_data_certification_identifier=f"cert:{asset_class.value}:market",
        analytical_evidence_certification_identifier=f"cert:{asset_class.value}:evidence",
        execution_certification_identifier=f"cert:{asset_class.value}:execution",
        custody_settlement_identifier=f"cert:{asset_class.value}:custody",
        source_identifiers=(f"source:{asset_class.value}",),
        limitations=("synthetic acceptance fixture; not production activation",),
    )


def _approve(
    store: SQLiteAssetClassApprovalStore,
    asset_class: CandidateAssetClass,
) -> AssetClassApproval:
    approval = AssetClassApproval(
        identifier=f"approval:{asset_class.value}:paper-v1",
        profile=_profile(asset_class),
        approved_at=AS_OF - timedelta(days=2),
        effective_at=AS_OF - timedelta(days=1),
        expires_at=AS_OF + timedelta(days=30),
        governance_identifier="governance:fixture-review",
        process_version="investment-process.development",
        code_version="commit:test",
        rationale="Synthetic acceptance approval for policy testing only.",
    )
    store.append(approval)
    return approval


def _snapshot() -> tuple[
    PointInTimeSecurityMasterSnapshot,
    tuple[SecurityMasterMarketMetrics, ...],
]:
    global_equity = Instrument(
        instrument_id="GLOBAL:EQUITY:LSE:SHEL",
        name="Shell plc",
        asset_class=AssetClass.EQUITY,
        instrument_type=InstrumentType.COMMON_STOCK,
    )
    fx = Instrument(
        instrument_id="FX:EBS:EURUSD:SPOT",
        name="Euro / U.S. Dollar",
        asset_class=AssetClass.FX,
        instrument_type=InstrumentType.SPOT,
        base_asset="EUR",
        quote_currency="USD",
        settlement_currency="USD",
    )
    crypto = Instrument(
        instrument_id="CRYPTO:COINBASE:BTC-USD:SPOT",
        name="Bitcoin / U.S. Dollar",
        asset_class=AssetClass.CRYPTO,
        instrument_type=InstrumentType.SPOT,
        base_asset="BTC",
        quote_currency="USD",
        settlement_currency="USD",
    )
    snapshot = PointInTimeSecurityMasterSnapshot(
        identifier="security-master:multi-asset:test",
        catalog_identifier="catalog:multi-asset:test",
        catalog_version="fixture.v1",
        as_of=AS_OF,
        knowledge_cutoff=AS_OF,
        issuers=(),
        instruments=tuple(
            _instrument_record(item) for item in (global_equity, fx, crypto)
        ),
        identifiers=(),
        listings=(
            _listing(
                global_equity,
                venue="LSE",
                symbol="SHEL",
                country="GB",
                calendar=TradingCalendar.EXCHANGE,
            ),
            _listing(
                fx,
                venue="EBS",
                symbol="EURUSD",
                country="GLOBAL",
                calendar=TradingCalendar.CONTINUOUS,
            ),
            _listing(
                crypto,
                venue="COINBASE",
                symbol="BTC-USD",
                country="GLOBAL",
                calendar=TradingCalendar.CONTINUOUS,
            ),
        ),
        actions=(),
        coverage=_coverage(),
    )
    return snapshot, tuple(
        _metric(item) for item in (global_equity, fx, crypto)
    )


def test_multi_asset_builder_excludes_every_unapproved_market(tmp_path: Path) -> None:
    snapshot, metrics = _snapshot()
    authority = AssetClassScopeAuthority(
        SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    )
    builder = MultiAssetUniverseBuilder(
        RecommendationUniversePolicy(asset_class_authority=authority)
    )

    universe = builder.build(snapshot, metrics)

    assert universe.constituents == ()
    assert len(universe.exclusions) == 3
    assert all(
        "no active asset-class governance approval" in item.reasons[0]
        for item in universe.exclusions
    )


def test_multi_asset_builder_preserves_approval_lineage_for_all_markets(
    tmp_path: Path,
) -> None:
    snapshot, metrics = _snapshot()
    store = SQLiteAssetClassApprovalStore(tmp_path / "governance.db")
    approvals = {
        asset_class: _approve(store, asset_class)
        for asset_class in (
            CandidateAssetClass.INTERNATIONAL_EQUITY,
            CandidateAssetClass.FX,
            CandidateAssetClass.CRYPTO,
        )
    }
    builder = MultiAssetUniverseBuilder(
        RecommendationUniversePolicy(
            version="recommendation-universe.multi-asset-development.v1",
            asset_class_authority=AssetClassScopeAuthority(store),
        )
    )

    universe = builder.build(snapshot, metrics)

    assert universe.authoritative is True
    assert universe.exclusions == ()
    assert tuple(
        item.instrument.asset_class for item in universe.constituents
    ) == (
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FX,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
    )
    for item in universe.constituents:
        expected = approvals[item.instrument.asset_class]
        assert item.assessment.asset_class_approval_identifier == expected.identifier
        assert item.membership.source_identifier.endswith(expected.identifier)
