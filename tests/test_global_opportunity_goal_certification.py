"""Certification tests for the 'best opportunity anywhere' compounding objective."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from cio import CandidateAssetClass
from evaluation.global_market_coverage import (
    GlobalOpportunityRegion,
    build_global_market_coverage_report,
    opportunity_region,
)
from operations.active_paper_universe import load_active_paper_universe_for_publication
from operations.free_paper_pilot import (
    FreePaperPilotInstrument,
    load_free_paper_pilot_universe,
    write_active_paper_universe,
)
from operations.global_opportunity_reassessment import (
    GlobalOpportunityMaterialCIOReassessmentEngine,
)
from operations.instrument_eligibility_factory import AutomaticInstrumentEligibilityFactory
from operations.production_capability_authority import _candidate_evidence, _policy
from operations.universal_capability_graph import AssetFamily, evaluate_capabilities
from operations.universal_paper_contract import (
    NormalizedInvestmentView,
    PaperOrderIntent,
    translate_paper_intent,
)
from portfolio.marginal_compounding_value import assess_marginal_compounding_value
from tests.cio_test_fixtures import AS_OF, build_candidate


def _candidate(
    symbol: str,
    *,
    asset_class: CandidateAssetClass,
    country: str,
    expected_return_shift: float,
    opportunity_cost_return: float = 0.04,
):
    base = build_candidate(
        symbol=symbol,
        expected_return_shift=expected_return_shift,
    )
    instrument = replace(
        base.instrument,
        asset_class=asset_class,
        country_code=country,
        instrument_type=(
            "token"
            if asset_class is CandidateAssetClass.CRYPTO
            else "future"
            if asset_class in {CandidateAssetClass.COMMODITY, CandidateAssetClass.FUTURE}
            else "bond"
            if asset_class is CandidateAssetClass.FIXED_INCOME
            else "equity"
        ),
    )
    return replace(
        base,
        instrument=instrument,
        opportunity_cost_return=opportunity_cost_return,
    )


def test_crypto_bull_run_beats_mediocre_us_equity_on_common_compounding_scale():
    us = _candidate(
        "USEQ",
        asset_class=CandidateAssetClass.US_EQUITY,
        country="US",
        expected_return_shift=-0.03,
    )
    crypto = _candidate(
        "BTCUSD",
        asset_class=CandidateAssetClass.CRYPTO,
        country="US",
        expected_return_shift=0.16,
    )

    assert assess_marginal_compounding_value(crypto).utility > assess_marginal_compounding_value(us).utility


def test_commodity_leadership_can_replace_weak_crypto():
    crypto = _candidate(
        "BTCUSD",
        asset_class=CandidateAssetClass.CRYPTO,
        country="US",
        expected_return_shift=-0.09,
    )
    copper = _candidate(
        "HG",
        asset_class=CandidateAssetClass.COMMODITY,
        country="US",
        expected_return_shift=0.12,
    )

    assert assess_marginal_compounding_value(copper).utility > assess_marginal_compounding_value(crypto).utility


def test_fixed_income_can_win_when_risky_assets_are_unattractive():
    equity = _candidate(
        "RISK",
        asset_class=CandidateAssetClass.US_EQUITY,
        country="US",
        expected_return_shift=-0.14,
    )
    bond = _candidate(
        "BOND",
        asset_class=CandidateAssetClass.FIXED_INCOME,
        country="US",
        expected_return_shift=-0.01,
        opportunity_cost_return=0.02,
    )

    assert assess_marginal_compounding_value(bond).utility > assess_marginal_compounding_value(equity).utility


def test_cash_remains_valid_when_every_candidate_fails_the_hurdle():
    weak = _candidate(
        "WEAK",
        asset_class=CandidateAssetClass.US_EQUITY,
        country="US",
        expected_return_shift=-0.24,
        opportunity_cost_return=0.06,
    )

    assert assess_marginal_compounding_value(weak).utility < 0.0


def test_japanese_equity_beats_us_equity_when_its_economics_are_better():
    us = _candidate(
        "US",
        asset_class=CandidateAssetClass.US_EQUITY,
        country="US",
        expected_return_shift=-0.01,
    )
    japan = _candidate(
        "JP",
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        country="JP",
        expected_return_shift=0.08,
    )

    assert opportunity_region(japan) is GlobalOpportunityRegion.JAPAN
    assert assess_marginal_compounding_value(japan).utility > assess_marginal_compounding_value(us).utility


def test_best_observed_dynamic_instrument_cannot_be_owned_without_capability_authority(tmp_path):
    baseline = load_free_paper_pilot_universe()
    dynamic = FreePaperPilotInstrument(
        symbol="ACME",
        instrument_identifier="instrument:acme",
        name="ACME Corporation",
        execution_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure="us_equity",
        venue="NASDAQ",
        country_code="US",
        currency="USD",
        instrument_type="equity",
        maximum_weight=0.05,
    )
    universe = replace(
        baseline,
        identifier="free-paper-pilot:dynamic-certification-test",
        instruments=(*baseline.instruments, dynamic),
    )
    active_path = tmp_path / "active-paper-universe.json"
    publication_identifier = "eligible-universe:test:dynamic"
    write_active_paper_universe(
        universe,
        eligible_universe_publication_identifier=publication_identifier,
        destination=active_path,
    )

    without_authority = load_active_paper_universe_for_publication(
        publication_identifier,
        path=active_path,
        evaluated_at=AS_OF,
    )
    assert "ACME" not in without_authority.symbol_map

    candidate = build_candidate(symbol="ACME", expected_return_shift=0.20)
    candidate = replace(
        candidate,
        instrument=replace(candidate.instrument, instrument_type="equity"),
        review_at=AS_OF + timedelta(hours=12),
    )
    evidence = _candidate_evidence(
        candidate,
        dynamic,
        universe_identifier=universe.identifier,
        evaluated_at=AS_OF,
    )
    evaluation = evaluate_capabilities(evidence, evaluated_at=AS_OF)
    assert evaluation.certifiable is True

    from governance.instrument_paper_eligibility import SQLiteInstrumentPaperEligibilityStore

    store = SQLiteInstrumentPaperEligibilityStore(
        tmp_path / "instrument-paper-eligibility.db"
    )
    AutomaticInstrumentEligibilityFactory(store).reconcile(
        evidence,
        policy=_policy(
            instrument=dynamic,
            candidate=candidate,
            code_version="test",
        ),
        evaluated_at=AS_OF,
    )
    with_authority = load_active_paper_universe_for_publication(
        publication_identifier,
        path=active_path,
        evaluated_at=AS_OF,
    )
    assert with_authority.symbol_map["ACME"].instrument_identifier == "instrument:acme"


def test_fixed_income_universal_contract_uses_face_value_units():
    evaluation = SimpleNamespace(
        instrument_identifier="instrument:bond",
        certifiable=True,
    )
    # translate_paper_intent only needs the exact evaluation identity/certifiable flag.
    instruction = translate_paper_intent(
        PaperOrderIntent(
            instrument_identifier="instrument:bond",
            target_notional=995.0,
            side="buy",
        ),
        NormalizedInvestmentView(
            instrument_identifier="instrument:bond",
            asset_family=AssetFamily.FIXED_INCOME,
            reference_price=99.5,
            contract_multiplier=1.0,
            trading_currency="USD",
            settlement_currency="USD",
        ),
        evaluation,
    )
    assert instruction.signed_quantity == 1000.0
    assert instruction.notional == 995.0


def test_global_coverage_reports_geographic_blind_spots():
    us = _candidate(
        "USONLY",
        asset_class=CandidateAssetClass.US_EQUITY,
        country="US",
        expected_return_shift=0.04,
    )
    contexts = (
        SimpleNamespace(candidate_identifier=us.identifier, forward_intelligence=object()),
    )
    report = build_global_market_coverage_report(
        candidates=(us,),
        specialist_contexts=contexts,
        as_of=AS_OF,
        required_domains=(),
    )

    assert "japan" in report.missing_required_regions
    assert "europe" in report.missing_required_regions
    assert report.regional_rotation_ready is False


def test_cross_market_leadership_change_requests_reassessment():
    engine = object.__new__(GlobalOpportunityMaterialCIOReassessmentEngine)
    engine.leadership_spread_threshold = 0.02
    engine.leadership_change_threshold = 0.0125
    engine._symbol_domains = lambda: {  # type: ignore[method-assign]
        "SPY": "equity",
        "BTC": "crypto",
        "GLD": "commodity",
    }
    leader, reasons, scores = engine._leadership_change(
        state={
            "assessment_prices": {"SPY": 100.0, "BTC": 100.0, "GLD": 100.0},
            "last_prices": {"SPY": 101.0, "BTC": 110.0, "GLD": 103.0},
            "global_opportunity_leader_domain": "equity",
            "global_opportunity_leader_score": 0.01,
        }
    )

    assert leader == "crypto"
    assert scores["crypto"] == 0.10
    assert any("rotated from equity to crypto" in reason for reason in reasons)
