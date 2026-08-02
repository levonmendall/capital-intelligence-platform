"""Shared test configuration."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import core.database as database
from core.seed import seed_mandates


@pytest.fixture(autouse=True)
def isolated_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Create and seed a temporary database for every test."""

    database_path = tmp_path / "capital_intelligence_test.db"

    monkeypatch.setattr(
        database,
        "DATABASE_FILE",
        database_path,
    )

    database.initialize_database()
    seed_mandates()

    yield database_path


@pytest.fixture(autouse=True)
def governed_adapter_instrument_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
):
    """Complete the exact SPY authority used by the governed adapter fixture.

    The certified eligible-universe publication proves screening coverage. The new
    ownership contract separately requires exact instrument capabilities before the
    integration fixture may produce a positive portfolio construction.
    """

    if request.node.path.name != "test_canonical_production_context_adapter.py":
        yield None
        return

    from cio import CandidateAssetClass
    from governance.instrument_paper_eligibility import (
        InstrumentPaperEligibilityCertification,
        InstrumentPaperEligibilityState,
        SQLiteInstrumentPaperEligibilityStore,
    )

    as_of = datetime(2026, 7, 27, 11, tzinfo=timezone.utc)
    authority_path = tmp_path / "instrument-paper-eligibility.db"
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_INSTRUMENT_PAPER_ELIGIBILITY_DATABASE",
        str(authority_path),
    )
    SQLiteInstrumentPaperEligibilityStore(authority_path).append(
        InstrumentPaperEligibilityCertification(
            identifier="instrument-paper-certification:spy:canonical-adapter:v1",
            instrument_identifier="instrument:spy",
            symbol="SPY",
            asset_class=CandidateAssetClass.US_ETF,
            venue="NYSE",
            country_code="US",
            instrument_type="other",
            state=InstrumentPaperEligibilityState.CERTIFIED,
            approved_at=as_of - timedelta(days=1),
            effective_at=as_of - timedelta(hours=1),
            expires_at=as_of + timedelta(days=30),
            minimum_average_daily_dollar_volume=5_000_000.0,
            maximum_position_weight=0.10,
            maximum_participation_rate=0.01,
            maximum_gross_leverage=1.0,
            market_data_certification_identifier="market-data:spy:canonical-adapter",
            identity_certification_identifier="identity:spy:canonical-adapter",
            evidence_certification_identifier="evidence:spy:canonical-adapter",
            valuation_model_version="etf-valuation.v1",
            trading_calendar_certification_identifier="calendar:nyse:v1",
            transaction_cost_model_version="us-etf-costs.v1",
            liquidity_model_version="us-etf-liquidity.v1",
            accounting_model_version="cash-security-accounting.v1",
            execution_model_version="paper-us-etf-execution.v1",
            risk_model_version="us-etf-risk.v1",
            portfolio_construction_model_version="canonical-construction.v1",
            custody_settlement_identifier="paper-broker-custody.v1",
            asset_class_approval_identifier="asset-class:us-etf-paper.v1",
            governance_identifier="governance:canonical-adapter-test",
            process_version="instrument-paper-eligibility.v1",
            code_version="test",
            source_identifiers=(
                "source:security-master:spy",
                "source:market-data:spy",
                "source:execution-model:spy",
            ),
        )
    )

    yield authority_path
