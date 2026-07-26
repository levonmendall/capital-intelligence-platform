"""Tests for SEC normalization, company factors, and CIO candidate generation."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from company import (
    CompanyAnalysisEngine,
    CompanyCandidateBuilder,
    CompanyFactor,
    CompanyFactNormalizer,
    CompanyMarketSnapshot,
    CompanyRegimeContext,
    FinancialHistory,
    NormalizedAnnualFinancials,
)
from data.filing import CompanyFact
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunitySetContext,
)


AS_OF = datetime(2026, 4, 1, 16, tzinfo=timezone.utc)


def _fact(
    *,
    year: int,
    tag: str,
    value: float,
    instant: bool = False,
    accepted_at: datetime | None = None,
    accession: str | None = None,
    form: str = "10-K",
    unit: str = "USD",
) -> CompanyFact:
    accepted = accepted_at or datetime(
        year + 1,
        2,
        15,
        16,
        tzinfo=timezone.utc,
    )
    return CompanyFact(
        cik="0000123456",
        taxonomy="us-gaap",
        tag=tag,
        unit=unit,
        value=value,
        period_start=None if instant else date(year, 1, 1),
        period_end=date(year, 12, 31),
        filed_at=accepted.date(),
        accepted_at=accepted,
        retrieved_at=max(AS_OF, accepted),
        accession_number=accession or f"{year}-{tag}",
        form=form,
        fiscal_year=year,
        fiscal_period="FY",
    )


def _year_facts(
    year: int,
    *,
    revenue: float,
    operating_income: float,
    net_income: float,
    operating_cash_flow: float,
    capex: float,
    assets: float,
    liabilities: float,
    equity: float,
    cash: float,
    current_debt: float,
    long_debt: float,
    current_assets: float,
    current_liabilities: float,
    shares: float,
) -> tuple[CompanyFact, ...]:
    return (
        _fact(
            year=year,
            tag="RevenueFromContractWithCustomerExcludingAssessedTax",
            value=revenue,
        ),
        _fact(year=year, tag="OperatingIncomeLoss", value=operating_income),
        _fact(year=year, tag="NetIncomeLoss", value=net_income),
        _fact(
            year=year,
            tag="NetCashProvidedByUsedInOperatingActivities",
            value=operating_cash_flow,
        ),
        _fact(
            year=year,
            tag="PaymentsToAcquirePropertyPlantAndEquipment",
            value=capex,
        ),
        _fact(year=year, tag="Assets", value=assets, instant=True),
        _fact(
            year=year,
            tag="Liabilities",
            value=liabilities,
            instant=True,
        ),
        _fact(
            year=year,
            tag="StockholdersEquity",
            value=equity,
            instant=True,
        ),
        _fact(
            year=year,
            tag="CashAndCashEquivalentsAtCarryingValue",
            value=cash,
            instant=True,
        ),
        _fact(
            year=year,
            tag="LongTermDebtAndFinanceLeaseObligationsCurrent",
            value=current_debt,
            instant=True,
        ),
        _fact(
            year=year,
            tag="LongTermDebtCurrent",
            value=current_debt * 0.8,
            instant=True,
        ),
        _fact(
            year=year,
            tag="LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            value=long_debt,
            instant=True,
        ),
        _fact(
            year=year,
            tag="LongTermDebtNoncurrent",
            value=long_debt * 0.9,
            instant=True,
        ),
        _fact(
            year=year,
            tag="AssetsCurrent",
            value=current_assets,
            instant=True,
        ),
        _fact(
            year=year,
            tag="LiabilitiesCurrent",
            value=current_liabilities,
            instant=True,
        ),
        _fact(
            year=year,
            tag="WeightedAverageNumberOfDilutedSharesOutstanding",
            value=shares,
            unit="shares",
        ),
    )


def _strong_history() -> FinancialHistory:
    facts = (
        *_year_facts(
            2023,
            revenue=1000,
            operating_income=180,
            net_income=140,
            operating_cash_flow=190,
            capex=50,
            assets=1500,
            liabilities=600,
            equity=900,
            cash=250,
            current_debt=30,
            long_debt=170,
            current_assets=600,
            current_liabilities=250,
            shares=100,
        ),
        *_year_facts(
            2024,
            revenue=1220,
            operating_income=235,
            net_income=185,
            operating_cash_flow=245,
            capex=55,
            assets=1650,
            liabilities=620,
            equity=1030,
            cash=300,
            current_debt=25,
            long_debt=150,
            current_assets=680,
            current_liabilities=255,
            shares=98,
        ),
        *_year_facts(
            2025,
            revenue=1500,
            operating_income=315,
            net_income=245,
            operating_cash_flow=310,
            capex=60,
            assets=1850,
            liabilities=650,
            equity=1200,
            cash=390,
            current_debt=20,
            long_debt=130,
            current_assets=790,
            current_liabilities=260,
            shares=96,
        ),
    )
    return CompanyFactNormalizer(minimum_annual_periods=3).normalize(
        tuple(facts),
        as_of=AS_OF,
    )


def _weak_history() -> FinancialHistory:
    periods = (
        NormalizedAnnualFinancials(
            cik="0000654321",
            fiscal_year=2023,
            period_end=date(2023, 12, 31),
            available_at=datetime(2024, 2, 15, tzinfo=timezone.utc),
            accession_numbers=("weak-2023",),
            source_fact_identifiers=("weak:2023",),
            revenue=1000,
            operating_income=50,
            net_income=20,
            operating_cash_flow=30,
            capital_expenditures=50,
            assets=2000,
            liabilities=1600,
            equity=400,
            cash=50,
            debt=1100,
            current_assets=300,
            current_liabilities=500,
            diluted_shares=100,
        ),
        NormalizedAnnualFinancials(
            cik="0000654321",
            fiscal_year=2024,
            period_end=date(2024, 12, 31),
            available_at=datetime(2025, 2, 15, tzinfo=timezone.utc),
            accession_numbers=("weak-2024",),
            source_fact_identifiers=("weak:2024",),
            revenue=940,
            operating_income=20,
            net_income=-10,
            operating_cash_flow=5,
            capital_expenditures=55,
            assets=1950,
            liabilities=1650,
            equity=300,
            cash=35,
            debt=1200,
            current_assets=260,
            current_liabilities=540,
            diluted_shares=108,
        ),
        NormalizedAnnualFinancials(
            cik="0000654321",
            fiscal_year=2025,
            period_end=date(2025, 12, 31),
            available_at=datetime(2026, 2, 15, tzinfo=timezone.utc),
            accession_numbers=("weak-2025",),
            source_fact_identifiers=("weak:2025",),
            revenue=850,
            operating_income=-30,
            net_income=-80,
            operating_cash_flow=-20,
            capital_expenditures=60,
            assets=1800,
            liabilities=1650,
            equity=150,
            cash=20,
            debt=1300,
            current_assets=220,
            current_liabilities=590,
            diluted_shares=120,
        ),
    )
    return FinancialHistory(
        cik="0000654321",
        as_of=AS_OF,
        periods=periods,
        normalization_version="company-financial-normalization.v1",
    )


def _market(*, strong: bool) -> CompanyMarketSnapshot:
    return CompanyMarketSnapshot(
        as_of=AS_OF,
        current_price=25.0 if strong else 45.0,
        market_cap=2500.0 if strong else 5000.0,
        shares_outstanding=100.0,
        dividend_per_share=0.25 if strong else 0.0,
        six_month_return=0.18 if strong else -0.20,
        twelve_month_return=0.30 if strong else -0.35,
        benchmark_twelve_month_return=0.12,
        annualized_volatility=0.24 if strong else 0.65,
        maximum_drawdown=-0.18 if strong else -0.60,
        moving_average_200=22.0 if strong else 55.0,
        average_daily_dollar_volume=200_000_000.0 if strong else 6_000_000.0,
        data_age_hours=1.0,
        evidence_identifiers=("market:snapshot",),
    )


def _regime(*, supportive: bool) -> CompanyRegimeContext:
    value = 0.60 if supportive else -0.50
    return CompanyRegimeContext(
        as_of=AS_OF,
        growth_support=value,
        liquidity_support=value,
        credit_support=value,
        market_risk_support=value,
        industry_cyclicality=0.50,
        duration_sensitivity=0.40,
        evidence_identifiers=("regime:snapshot",),
    )


def test_normalizer_excludes_future_amendment_until_accepted() -> None:
    original = _fact(
        year=2025,
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        value=1000,
        accepted_at=datetime(2026, 2, 15, tzinfo=timezone.utc),
        accession="original",
    )
    amendment = _fact(
        year=2025,
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        value=1100,
        accepted_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        accession="amendment",
        form="10-K/A",
    )

    before = CompanyFactNormalizer().normalize(
        (original, amendment),
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    after = CompanyFactNormalizer().normalize(
        (original, amendment),
        as_of=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    assert before.latest.revenue == pytest.approx(1000)
    assert before.latest.accession_numbers == ("original",)
    assert after.latest.revenue == pytest.approx(1100)
    assert after.latest.accession_numbers == ("amendment",)


def test_normalizer_uses_preferred_debt_tags_without_double_counting() -> None:
    history = _strong_history()

    assert history.latest.debt == pytest.approx(150.0)
    assert history.latest.cash_to_debt == pytest.approx(2.6)


def test_normalized_financials_produce_derived_metrics_without_filling_missing() -> None:
    latest = _strong_history().latest

    assert latest.free_cash_flow == pytest.approx(250.0)
    assert latest.operating_margin == pytest.approx(0.21)
    assert latest.free_cash_flow_margin == pytest.approx(1 / 6)
    assert latest.current_ratio == pytest.approx(790 / 260)
    assert latest.return_on_invested_capital() is not None

    incomplete = replace(
        latest,
        operating_cash_flow=None,
        capital_expenditures=None,
    )
    assert incomplete.free_cash_flow is None
    assert incomplete.free_cash_flow_margin is None
    assert incomplete.coverage < latest.coverage


def test_company_engine_publishes_all_eight_factors() -> None:
    analysis = CompanyAnalysisEngine().analyze(
        symbol="ACME",
        history=_strong_history(),
        market=_market(strong=True),
        regime=_regime(supportive=True),
    )

    assert {item.factor for item in analysis.factors} == set(CompanyFactor)
    assert all(-1.0 <= item.score <= 1.0 for item in analysis.factors)
    assert all(0.0 <= item.confidence <= 1.0 for item in analysis.factors)
    assert analysis.evidence_quality.point_in_time_integrity == 1.0
    assert analysis.confidence <= analysis.evidence_quality.ceiling
    assert len(analysis.evidence_identifiers) >= 5


def test_strong_company_scores_above_deteriorating_company() -> None:
    engine = CompanyAnalysisEngine()
    strong = engine.analyze(
        symbol="ACME",
        history=_strong_history(),
        market=_market(strong=True),
        regime=_regime(supportive=True),
    )
    weak = engine.analyze(
        symbol="WEAK",
        history=_weak_history(),
        market=_market(strong=False),
        regime=_regime(supportive=False),
    )

    assert strong.overall_score > weak.overall_score
    assert strong.factor(CompanyFactor.QUALITY).score > weak.factor(
        CompanyFactor.QUALITY
    ).score
    assert strong.factor(CompanyFactor.FINANCIAL_STRENGTH).score > weak.factor(
        CompanyFactor.FINANCIAL_STRENGTH
    ).score
    assert strong.factor(CompanyFactor.GROWTH).score > weak.factor(
        CompanyFactor.GROWTH
    ).score
    assert strong.factor(CompanyFactor.MOMENTUM).score > weak.factor(
        CompanyFactor.MOMENTUM
    ).score
    assert strong.factor(CompanyFactor.COMPANY_RISK).score > weak.factor(
        CompanyFactor.COMPANY_RISK
    ).score


def test_company_candidate_populates_common_quantitative_schema() -> None:
    analysis = CompanyAnalysisEngine().analyze(
        symbol="ACME",
        history=_strong_history(),
        market=_market(strong=True),
        regime=_regime(supportive=True),
    )

    candidate = CompanyCandidateBuilder().build(
        analysis,
        instrument_id="instrument:acme",
        venue="NASDAQ",
        opportunity_cost_return=0.04,
        maximum_position_weight=0.08,
    )

    assert candidate.base_case_probability == pytest.approx(0.55)
    assert candidate.bull_case_probability == pytest.approx(0.25)
    assert candidate.bear_case_probability == pytest.approx(0.20)
    assert candidate.probability_weighted_expected_return != 0.0
    assert candidate.estimated_fair_value > 0.0
    assert candidate.expected_downside < candidate.base_case_return
    assert candidate.model_versions == (
        "company-financial-normalization.v1",
        "company-analysis.v1",
        "company-expected-return.v1",
    )
    assert "retirement" not in repr(candidate).lower()
    assert "goal" not in repr(candidate).lower()


def test_strong_company_candidate_can_enter_opportunity_queue() -> None:
    analysis = CompanyAnalysisEngine().analyze(
        symbol="ACME",
        history=_strong_history(),
        market=_market(strong=True),
        regime=_regime(supportive=True),
    )
    candidate = CompanyCandidateBuilder().build(
        analysis,
        instrument_id="instrument:acme",
        venue="NASDAQ",
        opportunity_cost_return=0.04,
        maximum_position_weight=0.08,
    )
    context = OpportunitySetContext(
        identifier="opportunity-set:company-test",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash:treasury-bills",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=1.0,
            ),
        ),
    )

    queue = OpportunityEngine().build_queue((candidate,), context)

    assert queue.has_qualified_opportunity
    assert queue.top is not None
    assert queue.top.candidate.instrument.symbol == "ACME"


def test_company_candidate_policy_is_versioned_hypothesis_not_hidden_precision() -> None:
    analysis = CompanyAnalysisEngine().analyze(
        symbol="ACME",
        history=_strong_history(),
        market=_market(strong=True),
        regime=_regime(supportive=True),
    )
    candidate = CompanyCandidateBuilder().build(
        analysis,
        instrument_id="instrument:acme",
        venue="NASDAQ",
        opportunity_cost_return=0.04,
        maximum_position_weight=0.08,
    )

    assert "company-expected-return.v1" in candidate.model_versions
    assert any(
        "versioned expected-return mapping" in assumption
        for assumption in candidate.critical_assumptions
    )
    assert candidate.evidence_quality.independence < 1.0


def test_company_inputs_must_share_one_decision_timestamp() -> None:
    market = replace(
        _market(strong=True),
        as_of=AS_OF + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="share"):
        CompanyAnalysisEngine().analyze(
            symbol="ACME",
            history=_strong_history(),
            market=market,
            regime=_regime(supportive=True),
        )