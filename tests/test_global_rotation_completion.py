from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cio.models import CandidateAssetClass
from evaluation.global_market_coverage import build_global_market_coverage_report
from evaluation.global_rotation_performance import (
    GlobalRotationPerformancePolicy,
    RotationPerformanceObservation,
    build_global_rotation_performance_report,
)
from intelligence.causal_rotation import (
    CausalTransitionStage,
    assess_causal_opportunity,
)
from intelligence.forward import (
    ForwardIntelligenceBundle,
    ForwardSignal,
    ThemeStage,
    TrendStage,
)
from intelligence.mispriced_change import MispricedChangeState
from portfolio.global_compound_optimizer import optimize_global_compound_targets
from portfolio.global_hierarchy import (
    HierarchyLevel,
    build_global_opportunity_hierarchy,
)
from portfolio.global_rotation import GlobalOpportunityDomain

NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def _candidate(
    identifier: str,
    *,
    symbol: str,
    asset_class: CandidateAssetClass,
    name: str | None = None,
    country: str = "US",
    currency: str = "USD",
    industry: str = "memory",
    expected_return: float = 0.12,
    downside: float = -0.12,
    max_weight: float = 0.10,
):
    return SimpleNamespace(
        identifier=identifier,
        instrument=SimpleNamespace(
            instrument_id=f"instrument:{symbol}",
            symbol=symbol,
            name=name or symbol,
            asset_class=asset_class,
            economic_exposure_class=asset_class,
            country_code=country,
            currency=currency,
            industry=industry,
        ),
        net_expected_return=expected_return,
        expected_downside=downside,
        implementation_cost_return=0.002,
        maximum_position_weight=max_weight,
        decision_horizon_days=90,
        opportunity_cost_return=0.03,
        liquidity_score=0.90,
        evidence_quality=SimpleNamespace(score=0.85, ceiling=0.75),
        evidence_identifiers=(f"evidence:{identifier}",),
        current_portfolio_weight=0.0,
    )


class _Portfolio:
    as_of = NOW
    cash_weight = 0.20
    cash_expected_return = 0.04
    portfolio_value = 250_000.0

    def __init__(self, sectors=None, factors=None):
        self._sectors = sectors or {}
        self._factors = factors or {}

    def profile(self, candidate_identifier):
        return SimpleNamespace(
            candidate_identifier=candidate_identifier,
            sector=self._sectors.get(candidate_identifier, "technology"),
            factor_loadings=self._factors.get(candidate_identifier, (("growth", 0.5),)),
            correlation_bucket=self._sectors.get(candidate_identifier, "technology"),
        )

    def current_weight(self, _symbol):
        return 0.0


def test_hierarchy_ranks_domain_country_sector_industry_and_instrument():
    first = _candidate(
        "candidate:HBM",
        symbol="HBM",
        asset_class=CandidateAssetClass.US_EQUITY,
        industry="memory",
    )
    second = _candidate(
        "candidate:NET",
        symbol="NET",
        asset_class=CandidateAssetClass.US_EQUITY,
        industry="networking",
    )
    portfolio = _Portfolio(
        sectors={"candidate:HBM": "semiconductors", "candidate:NET": "networking"}
    )
    hierarchy = build_global_opportunity_hierarchy(
        candidates=(first, second),
        base_scores={"candidate:HBM": 0.86, "candidate:NET": 0.62},
        domains={"candidate:HBM": "equity", "candidate:NET": "equity"},
        portfolio=portfolio,
    )
    levels = {item.level for item in hierarchy.nodes}
    assert levels == set(HierarchyLevel)
    paths = {item.candidate_identifier: item for item in hierarchy.candidate_paths}
    assert paths[first.identifier].domain == "equity"
    assert paths[first.identifier].country_currency == "US / USD"
    assert paths[first.identifier].sector_theme.startswith("semiconductors / ")
    assert paths[first.identifier].industry == "memory"
    strengths = hierarchy.strength_by_candidate
    assert strengths[first.identifier] > strengths[second.identifier]
    assert hierarchy.authorizes_capital is False


def _theme_signal() -> ForwardSignal:
    return ForwardSignal(
        identifier="signal:theme:candidate:HBM",
        as_of=NOW,
        name="AI memory transmission",
        channels=("forecast", "fundamental"),
        expected_return_impact=0.01,
        confidence=0.85,
        evidence=("HBM demand is accelerating",),
        contradictory_evidence=("Estimated theme benefit already priced=20%",),
        assumptions=("AI capex persists",),
        risks=("capacity expands faster than demand",),
        change_conditions=("memory pricing weakens",),
        evidence_identifiers=("evidence:theme",),
    )


def test_causal_transition_promotes_explicit_underpriced_bottleneck_successor(monkeypatch):
    import intelligence.causal_rotation as module

    monkeypatch.setattr(
        module,
        "theme_successor_score",
        lambda _bundle: (0.90, ("evidence:successor",)),
    )
    monkeypatch.setattr(
        module,
        "assess_global_leadership_economics",
        lambda _bundle: SimpleNamespace(
            leadership_score=0.82,
            forward_confirmation=0.85,
            evidence_identifiers=("evidence:leadership",),
        ),
    )
    monkeypatch.setattr(
        module,
        "assess_mispriced_change",
        lambda _bundle: SimpleNamespace(
            state=MispricedChangeState.CONSTRUCTIVE,
            score=0.65,
            evidence_identifiers=("evidence:mispricing",),
        ),
    )
    bundle = ForwardIntelligenceBundle(
        identifier="forward:HBM",
        candidate_identifier="candidate:HBM",
        as_of=NOW,
        signals=(_theme_signal(),),
        scenarios=(),
        diagnostics=(
            "Theme successor rotation: HBM <- candidate:AI; zero-return-impact research propagation.",
            "Theme bottlenecks: memory=0.9",
        ),
        model_versions=("test.v1",),
        theme_stage=ThemeStage.SUPPLY_CONSTRAINED,
        trend_stage=TrendStage.BROADENING,
    )
    assessment = assess_causal_opportunity(bundle)
    assert assessment is not None
    assert assessment.stage is CausalTransitionStage.ACCELERATING_SUCCESSOR
    assert assessment.transition_probability >= 0.72
    assert assessment.pricing_gap == 0.80
    assert assessment.bottleneck_score == 0.90
    assert assessment.authorizes_capital is False


def test_global_compound_optimizer_respects_specialist_caps_and_cash_reserve():
    first = _candidate(
        "candidate:HBM",
        symbol="HBM",
        asset_class=CandidateAssetClass.US_EQUITY,
        expected_return=0.18,
        downside=-0.10,
    )
    second = _candidate(
        "candidate:GOLD",
        symbol="GOLD",
        asset_class=CandidateAssetClass.COMMODITY,
        expected_return=0.11,
        downside=-0.08,
    )
    signals = {
        first.identifier: SimpleNamespace(
            expected_return_edge=0.12,
            score=0.88,
            hierarchy_strength=0.86,
            causal_score=0.82,
            rank=1,
        ),
        second.identifier: SimpleNamespace(
            expected_return_edge=0.07,
            score=0.72,
            hierarchy_strength=0.72,
            causal_score=0.45,
            rank=2,
        ),
    }
    portfolio = _Portfolio(
        sectors={first.identifier: "semiconductors", second.identifier: "metals"},
        factors={
            first.identifier: (("growth", 0.8),),
            second.identifier: (("inflation", 0.8),),
        },
    )
    proposal = optimize_global_compound_targets(
        candidates=(first, second),
        rotation_context=SimpleNamespace(by_candidate=signals),
        conviction_targets={first.identifier: 0.07, second.identifier: 0.04},
        portfolio=portfolio,
        minimum_cash_weight=0.02,
    )
    targets = proposal.target_by_candidate
    assert 0.0 < targets[first.identifier] <= 0.07
    assert 0.0 < targets[second.identifier] <= 0.04
    assert proposal.target_cash_weight >= 0.02
    assert proposal.deployable_cash_used <= 0.18 + 1e-8
    assert proposal.deployable_cash_used > 0.0
    assert proposal.authorizes_capital is False
    assert proposal.construction_authority is False


def test_global_market_coverage_requires_cross_asset_decision_set():
    candidates = (
        _candidate("candidate:EQ", symbol="EQ", asset_class=CandidateAssetClass.US_EQUITY),
        _candidate("candidate:UST", symbol="UST", asset_class=CandidateAssetClass.FIXED_INCOME, name="Treasury duration"),
        _candidate("candidate:HY", symbol="HY", asset_class=CandidateAssetClass.FIXED_INCOME, name="Corporate credit"),
        _candidate("candidate:USD", symbol="USD", asset_class=CandidateAssetClass.FX),
        _candidate("candidate:OIL", symbol="OIL", asset_class=CandidateAssetClass.COMMODITY),
        _candidate("candidate:BTC", symbol="BTC", asset_class=CandidateAssetClass.CRYPTO),
    )
    contexts = tuple(
        SimpleNamespace(candidate_identifier=item.identifier, forward_intelligence=object())
        for item in candidates
    )
    report = build_global_market_coverage_report(
        candidates=candidates,
        specialist_contexts=contexts,
        as_of=NOW,
    )
    assert report.globally_rotation_ready is True
    assert report.missing_required_domains == ()
    assert report.investment_authority is False

    without_fx = tuple(item for item in candidates if item.instrument.asset_class is not CandidateAssetClass.FX)
    missing_report = build_global_market_coverage_report(
        candidates=without_fx,
        specialist_contexts=tuple(
            SimpleNamespace(candidate_identifier=item.identifier, forward_intelligence=object())
            for item in without_fx
        ),
        as_of=NOW,
    )
    assert GlobalOpportunityDomain.CURRENCY.value in missing_report.missing_required_domains
    assert missing_report.globally_rotation_ready is False


def test_walk_forward_rotation_performance_certifies_portfolio_behavior_across_regimes():
    regimes = ("tech_bull", "inflation", "dollar_bull", "equity_bear", "duration_rally")
    returns = (0.05, 0.03, 0.025, -0.01, 0.04)
    observations = tuple(
        RotationPerformanceObservation(
            identifier=f"obs:{index}",
            decision_as_of=NOW + timedelta(days=30 * index),
            outcome_observed_at=NOW + timedelta(days=30 * index + 20),
            regime=regime,
            portfolio_return_after_cost=returns[index],
            transaction_cost_return=0.001,
            turnover=0.12,
            ending_cash_weight=0.20,
            selected_domain=("equity", "commodity", "currency", "fixed_income", "fixed_income")[index],
            strongest_realized_domain=("equity", "commodity", "currency", "volatility", "fixed_income")[index],
            selected_rotation_return=(0.07, 0.05, 0.04, 0.01, 0.06)[index],
            strongest_available_return=(0.08, 0.06, 0.05, 0.03, 0.07)[index],
            equity_market_return=(0.08, -0.02, -0.01, -0.12, -0.03)[index],
            emerging_leadership_identified=True,
            leadership_lead_days=8.0,
            false_rotation=False,
            causal_transition_nominated=True,
            causal_transition_realized=index != 3,
            evidence_identifiers=(f"evidence:{index}",),
        )
        for index, regime in enumerate(regimes)
    )
    report = build_global_rotation_performance_report(
        observations=observations,
        as_of=observations[-1].outcome_observed_at + timedelta(days=1),
        policy=GlobalRotationPerformancePolicy(
            minimum_observations=5,
            minimum_regimes=5,
            maximum_false_rotation_rate=0.30,
            maximum_mean_cash_weight=0.55,
            minimum_causal_transition_hit_rate=0.50,
            minimum_leadership_capture_ratio=0.45,
            maximum_empirical_expected_shortfall=-0.20,
        ),
    )
    assert report.terminal_wealth_multiple > 1.0
    assert report.performance_behavior_certified is True
    assert report.mean_return_during_equity_contractions > 0.0
    assert report.leadership_capture_ratio is not None
    assert report.leadership_capture_ratio > 0.45
    assert report.performance_claim_authorized is False
    assert report.policy_change_authorized is False
    assert report.investment_authority is False
