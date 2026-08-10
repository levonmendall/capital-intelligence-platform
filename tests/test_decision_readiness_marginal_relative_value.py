from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

# Importing the production facade installs the production-only marginal targeting
# correction before the cycle is composed.
import application.production_context_executor  # noqa: F401
from application.cio_cycle import (
    CandidateExposureProfile,
    CanonicalCIOCycle,
    CyclePortfolioState,
)
from cio import CandidateAssetClass
from committee.specialists import MacroSpecialistContext
from governance.analytical_promotion import (
    AnalyticalPromotionCertification,
    ConservativeAnalyticalPromotion,
    ConservativeMacroOverlay,
)
from governance.decision_readiness import CandidateDecisionReadinessPolicy
from intelligence.asset_underwriting import UnderwritingDimension
from intelligence.value_of_information import ValueOfInformationEngine
from opportunity.relative_value import (
    RelativeValueAdmissionPolicy,
    RelativeValueCandidateExpression,
    RelativeValueExpressionType,
    RelativeValueLeg,
    RelativeValueLegSide,
)
from tests.cio_test_fixtures import AS_OF, build_candidate


@dataclass(frozen=True)
class _PaperEvidenceResult:
    candidates: tuple[object, ...]
    candidate_evidence: tuple[object, ...]
    holding_evidence: tuple[object, ...] = ()
    exclusions: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _evidence(candidate, *, company: bool, valuation: bool = True):
    return SimpleNamespace(
        candidate_identifier=candidate.identifier,
        macro=SimpleNamespace(evidence_identifiers=("macro:pit",)),
        company=object() if company else None,
        asset_valuation=object() if valuation else None,
        forward_intelligence=None,
        exposure_profile=None,
    )


def test_decision_readiness_filters_asset_specific_critical_gaps() -> None:
    equity = build_candidate(symbol="EQTY")
    crypto_base = build_candidate(symbol="CRYP")
    crypto = replace(
        crypto_base,
        instrument=replace(
            crypto_base.instrument,
            asset_class=CandidateAssetClass.CRYPTO,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
        ),
    )
    equity_evidence = _evidence(equity, company=True)
    crypto_evidence = _evidence(crypto, company=False)
    policy = CandidateDecisionReadinessPolicy()

    equity_readiness = policy.assess(equity, equity_evidence)
    crypto_readiness = policy.assess(crypto, crypto_evidence)

    assert equity_readiness.decision_ready is True
    assert crypto_readiness.decision_ready is False
    assert UnderwritingDimension.ONCHAIN in crypto_readiness.blocking_missing

    filtered = policy.filter_paper_evidence_result(
        _PaperEvidenceResult(
            candidates=(equity, crypto),
            candidate_evidence=(equity_evidence, crypto_evidence),
        )
    )
    assert tuple(item.identifier for item in filtered.candidates) == (equity.identifier,)
    assert tuple(item.candidate_identifier for item in filtered.candidate_evidence) == (
        equity.identifier,
    )
    assert filtered.exclusions[0][0] == crypto.instrument.instrument_id
    assert "onchain" in " ".join(filtered.exclusions[0][1]).lower()

    priorities = ValueOfInformationEngine().prioritize(readiness=crypto_readiness)
    assert priorities[0].blocking is True
    assert UnderwritingDimension.ONCHAIN in {
        item.dimension for item in priorities if item.blocking
    }
    assert all(item.authorizes_capital is False for item in priorities)


def test_marginal_targeting_respects_liquidity_instead_of_max_weight() -> None:
    base_candidate = build_candidate(symbol="NEWC")
    candidate = replace(
        base_candidate,
        instrument=replace(
            base_candidate.instrument,
            average_daily_dollar_volume=5_000.0,
        ),
    )
    portfolio = CyclePortfolioState(
        identifier="portfolio:marginal-test",
        as_of=AS_OF,
        portfolio_value=250_000.0,
        cash_weight=1.0,
        cash_expected_return=0.04,
        positions=(),
        exposure_profiles=(
            CandidateExposureProfile(
                candidate_identifier=candidate.identifier,
                sector="technology",
                factor_loadings=(),
                correlation_bucket="growth",
            ),
        ),
    )
    cycle = CanonicalCIOCycle()

    preview = cycle._preview_portfolio(
        candidate=candidate,
        rank=1,
        portfolio=portfolio,
        effective_opportunity_cost=0.04,
    )
    ranking = cycle.prepare_ranking_inputs((candidate,), portfolio)[0]

    # Default execution policy allows 10% of ADV per day for three days:
    # 5,000 * 10% * 3 / 250,000 = 0.6% maximum executable portfolio weight.
    assert preview.proposed_position_weight is not None
    assert 0.0 < preview.proposed_position_weight <= 0.006001
    assert preview.proposed_position_weight < candidate.maximum_position_weight
    assert ranking.marginal_portfolio_contribution > 0.0


def _leg(symbol: str, side: RelativeValueLegSide) -> RelativeValueLeg:
    return RelativeValueLeg(
        instrument_identifier=f"instrument:{symbol.lower()}",
        symbol=symbol,
        side=side,
        gross_weight=0.05,
        expected_return=0.10 if side is RelativeValueLegSide.LONG else -0.02,
        implementation_cost_return=0.001,
        financing_return=-0.002,
        liquidity_score=0.90,
        decision_ready=True,
        paper_execution_certified=True,
        evidence_identifiers=(f"market:{symbol.lower()}",),
    )


def test_relative_value_is_first_class_but_cannot_bypass_atomic_execution() -> None:
    expression = RelativeValueCandidateExpression(
        identifier="relative-value:pair:a-b",
        as_of=AS_OF,
        expression_type=RelativeValueExpressionType.PAIR,
        legs=(
            _leg("LONG", RelativeValueLegSide.LONG),
            _leg("SHORT", RelativeValueLegSide.SHORT),
        ),
        thesis="Long leg has superior governed expected return versus the matched hedge.",
        base_case_return=0.06,
        bull_case_return=0.12,
        bear_case_return=-0.05,
        base_probability=0.60,
        bull_probability=0.20,
        bear_probability=0.20,
        maximum_loss_return=-0.20,
        evidence_identifiers=("pair:evidence",),
        model_versions=("relative-value.v1",),
        atomic_paper_execution_certified=False,
    )
    admission = RelativeValueAdmissionPolicy().assess(expression)
    assert admission.research_eligible is True
    assert admission.cio_review_eligible is True
    assert admission.paper_execution_eligible is False
    assert admission.authorizes_capital is False

    certified = replace(expression, atomic_paper_execution_certified=True)
    certified_admission = RelativeValueAdmissionPolicy().assess(certified)
    assert certified_admission.paper_execution_eligible is True
    assert certified_admission.authorizes_capital is False

    with pytest.raises(ValueError, match="cannot independently authorize"):
        replace(expression, investment_authority=True)


def test_certified_shadow_promotion_can_only_make_macro_more_conservative() -> None:
    macro = MacroSpecialistContext(
        as_of=AS_OF,
        regime="constructive_growth",
        expected_return_impact=0.05,
        confidence=0.80,
        tailwinds=("growth",),
        headwinds=(),
        systemic_risks=("policy uncertainty",),
        scenarios=("base",),
        evidence_identifiers=("macro:base",),
    )
    overlay = ConservativeMacroOverlay(
        identifier="global-macro:certified:v1",
        as_of=AS_OF - timedelta(minutes=5),
        regime_label="global_growth_slowdown",
        expected_return_impact=-0.02,
        confidence_ceiling=0.60,
        headwinds=("global growth is slowing",),
        systemic_risks=("cross-region recession risk",),
        evidence_identifiers=("macro:global",),
    )
    certification = AnalyticalPromotionCertification(
        identifier="promotion:global-macro:v1",
        artifact_identifier=overlay.identifier,
        certified_at=AS_OF - timedelta(minutes=1),
        valid_until=AS_OF + timedelta(days=1),
        knowledge_cutoff=AS_OF - timedelta(minutes=5),
        historical_replay_passed=True,
        point_in_time_passed=True,
        calibration_passed=True,
        decision_certified=True,
        evidence_identifiers=("certification:global-macro",),
    )

    promoted = ConservativeAnalyticalPromotion.apply_macro_overlay(
        macro, overlay, certification
    )
    assert promoted.expected_return_impact == -0.02
    assert promoted.expected_return_impact <= macro.expected_return_impact
    assert promoted.confidence == 0.60
    assert promoted.confidence <= macro.confidence
