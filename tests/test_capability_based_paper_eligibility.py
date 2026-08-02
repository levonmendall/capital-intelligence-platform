from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from application.production_context_executor import _apply_runtime_position_cap
from cio import CandidateAssetClass, CandidateInstrument
from cio.universe import RecommendationUniversePolicy, UniverseDisposition
from governance.coverage_certification import load_market_coverage
from governance.instrument_paper_eligibility import (
    InstrumentPaperEligibilityAuthority,
    InstrumentPaperEligibilityCertification,
    InstrumentPaperEligibilityState,
    SQLiteInstrumentPaperEligibilityStore,
)
from governance.market_participation import CanonicalMarketParticipationAuthority
from operations.free_paper_pilot import load_free_paper_pilot_universe


UTC = timezone.utc
AS_OF = datetime(2026, 8, 1, 20, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CandidateEnvelope:
    instrument: CandidateInstrument
    maximum_position_weight: float


def _candidate(*, adv: float = 25_000_000.0) -> CandidateInstrument:
    return CandidateInstrument(
        instrument_id="instrument:us-equity:aapl",
        symbol="AAPL",
        name="Apple Inc.",
        asset_class=CandidateAssetClass.US_EQUITY,
        venue="NASDAQ",
        country_code="US",
        average_daily_dollar_volume=adv,
        data_age_hours=1.0,
        analytical_coverage=0.98,
        security_master_snapshot_identifier="security-master:2026-08-01",
        security_master_record_identifiers=("security-master-record:aapl",),
        instrument_type="common_stock",
    )


def _certification(**overrides) -> InstrumentPaperEligibilityCertification:
    values = {
        "identifier": "instrument-paper-certification:aapl:v1",
        "instrument_identifier": "instrument:us-equity:aapl",
        "symbol": "AAPL",
        "asset_class": CandidateAssetClass.US_EQUITY,
        "venue": "NASDAQ",
        "country_code": "US",
        "instrument_type": "common_stock",
        "state": InstrumentPaperEligibilityState.CERTIFIED,
        "approved_at": AS_OF - timedelta(days=1),
        "effective_at": AS_OF - timedelta(hours=1),
        "expires_at": AS_OF + timedelta(days=90),
        "minimum_average_daily_dollar_volume": 2_000_000.0,
        "maximum_position_weight": 0.08,
        "maximum_participation_rate": 0.01,
        "maximum_gross_leverage": 1.0,
        "market_data_certification_identifier": "market-data:aapl:v1",
        "identity_certification_identifier": "identity:aapl:v1",
        "evidence_certification_identifier": "evidence:aapl:v1",
        "valuation_model_version": "equity-valuation.v1",
        "trading_calendar_certification_identifier": "calendar:nasdaq:v1",
        "transaction_cost_model_version": "equity-costs.v1",
        "liquidity_model_version": "equity-liquidity.v1",
        "accounting_model_version": "cash-security-accounting.v1",
        "execution_model_version": "paper-equity-execution.v1",
        "risk_model_version": "single-equity-risk.v1",
        "portfolio_construction_model_version": "canonical-construction.v1",
        "custody_settlement_identifier": "paper-broker-custody.v1",
        "asset_class_approval_identifier": "asset-class:us-equity-paper.v1",
        "governance_identifier": "governance:instrument-paper-eligibility",
        "process_version": "instrument-paper-eligibility.v1",
        "code_version": "test",
        "source_identifiers": (
            "source:security-master",
            "source:market-data",
            "source:execution-model",
        ),
    }
    values.update(overrides)
    return InstrumentPaperEligibilityCertification(**values)


def _participation(store) -> CanonicalMarketParticipationAuthority:
    return CanonicalMarketParticipationAuthority(
        load_market_coverage("config/market_coverage_registry.v1.json"),
        instrument_authority=InstrumentPaperEligibilityAuthority(store),
    )


def test_complete_active_certification_makes_liquid_instrument_allocatable(
    tmp_path,
) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    certification = _certification()
    store.append(certification)
    authority = InstrumentPaperEligibilityAuthority(store)

    assessment = authority.assess(_candidate(), evaluated_at=AS_OF)

    assert assessment.paper_allocatable is True
    assert assessment.certification_identifier == certification.identifier
    assert assessment.maximum_position_weight == 0.08
    assert store.verify_integrity() is True


def test_certification_fails_closed_when_current_liquidity_is_below_floor(
    tmp_path,
) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    store.append(_certification())

    assessment = InstrumentPaperEligibilityAuthority(store).assess(
        _candidate(adv=1_000_000.0),
        evaluated_at=AS_OF,
    )

    assert assessment.paper_allocatable is False
    assert "current liquidity is below the certified floor" in assessment.reasons


def test_identity_mismatch_cannot_reuse_another_instruments_certification(
    tmp_path,
) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    store.append(_certification())
    mismatched = replace(_candidate(), symbol="MSFT")

    assessment = InstrumentPaperEligibilityAuthority(store).assess(
        mismatched,
        evaluated_at=AS_OF,
    )

    assert assessment.paper_allocatable is False
    assert "symbol does not match the certification" in assessment.reasons


def test_expired_or_suspended_certification_removes_portfolio_authority(
    tmp_path,
) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    store.append(
        _certification(
            identifier="instrument-paper-certification:aapl:expired",
            approved_at=AS_OF - timedelta(days=31),
            effective_at=AS_OF - timedelta(days=30),
            expires_at=AS_OF - timedelta(days=1),
        )
    )

    assessment = InstrumentPaperEligibilityAuthority(store).assess(
        _candidate(),
        evaluated_at=AS_OF,
    )

    assert assessment.paper_allocatable is False
    assert assessment.certification_identifier is None


def test_capability_certification_expands_portfolio_beyond_bootstrap_fifteen(
    tmp_path,
) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    store.append(_certification())
    participation = _participation(store)
    bootstrap = load_free_paper_pilot_universe()
    universe = SimpleNamespace(
        identifier="capability-based-universe:test",
        instruments=(*bootstrap.instruments, _candidate()),
        limitations=(),
    )

    governed = participation.decision_authority_universe(
        universe,
        evaluated_at=AS_OF,
    )
    identifiers = {
        getattr(item, "instrument_identifier", getattr(item, "instrument_id", ""))
        for item in governed.instruments
    }

    assert len(identifiers) == 16
    assert "instrument:us-equity:aapl" in identifiers
    assert participation.assess(
        instrument_identifier="instrument:us-equity:aapl",
        asset_class=CandidateAssetClass.US_EQUITY,
        instrument=_candidate(),
        evaluated_at=AS_OF,
    ).authority_kind == "instrument_capability_certification"


def test_production_policy_blocks_uncertified_core_asset_then_allows_certified_asset(
    tmp_path,
) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")

    def policy() -> RecommendationUniversePolicy:
        return RecommendationUniversePolicy(
            market_participation_authority=_participation(store),
        )

    candidate = _candidate(adv=3_000_000.0)
    blocked = policy().evaluate(candidate, as_of=AS_OF)
    assert blocked.disposition is UniverseDisposition.INTELLIGENCE_ONLY

    store.append(_certification())
    approved = policy().evaluate(candidate, as_of=AS_OF)

    assert approved.disposition is UniverseDisposition.DIRECT_RECOMMENDATION
    assert approved.maximum_position_weight == 0.08
    assert "instrument-paper-certification:aapl:v1" in approved.reasons[0]


def test_certified_position_cap_overrides_a_looser_analytical_cap(tmp_path) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    store.append(_certification(maximum_position_weight=0.06))
    candidate = CandidateEnvelope(
        instrument=_candidate(),
        maximum_position_weight=0.15,
    )

    capped = _apply_runtime_position_cap(
        candidate,
        authority=_participation(store),
        evaluated_at=AS_OF,
    )

    assert capped.maximum_position_weight == 0.06
    assert candidate.maximum_position_weight == 0.15


def test_unpublished_certified_instrument_fails_complete_universe_reconciliation(
    tmp_path,
) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    store.append(_certification())
    participation = _participation(store)
    bootstrap = load_free_paper_pilot_universe()

    with pytest.raises(ValueError, match="instrument:us-equity:aapl"):
        participation.require_complete_allocatable_set(
            bootstrap.instruments,
            evaluated_at=AS_OF,
        )


def test_complete_capability_fields_are_mandatory() -> None:
    with pytest.raises(ValueError, match="risk_model_version"):
        _certification(risk_model_version="")
