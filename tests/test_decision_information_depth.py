from __future__ import annotations

from types import SimpleNamespace

import pytest

from cio.models import CandidateAssetClass
from governance.decision_readiness import CandidateDecisionReadiness
from intelligence.asset_underwriting import UnderwritingCoverage, UnderwritingDimension
from intelligence.information_completeness import CandidateInformationCompleteness
from operations import decision_information_depth as module
from operations.decision_information_depth import (
    InformationDepthResolutionState,
    build_decision_information_depth_program,
)


def _readiness(
    identifier: str,
    *,
    asset_class: CandidateAssetClass,
    economic_class: CandidateAssetClass,
    missing: tuple[UnderwritingDimension, ...],
    blocking: tuple[UnderwritingDimension, ...],
    deep_missing: tuple[UnderwritingDimension, ...],
) -> CandidateDecisionReadiness:
    required = tuple(
        dict.fromkeys(
            (
                UnderwritingDimension.IDENTITY,
                UnderwritingDimension.MARKET_DATA,
                UnderwritingDimension.LIQUIDITY,
                UnderwritingDimension.MACRO,
                UnderwritingDimension.VALUATION,
                UnderwritingDimension.HISTORY,
                *missing,
            )
        )
    )
    available = tuple(item for item in required if item not in set(missing))
    coverage = UnderwritingCoverage(
        asset_class=asset_class,
        required=required,
        available=available,
        missing=missing,
        completeness=len(available) / len(required),
        decision_complete=not missing,
    )
    completeness = CandidateInformationCompleteness(
        candidate_identifier=identifier,
        coverage=coverage,
        available_reasons=("available",),
        missing_reasons=tuple(f"missing {item.value}" for item in missing),
    )
    return CandidateDecisionReadiness(
        candidate_identifier=identifier,
        asset_class=asset_class,
        coverage=coverage,
        blocking_required=blocking,
        blocking_missing=blocking,
        decision_ready=not blocking,
        reasons=("test readiness",),
        information_completeness=completeness,
        economic_exposure_class=economic_class,
        deep_required=deep_missing,
        deep_missing=deep_missing,
        deep_intelligence_complete=not deep_missing,
    )


class _Policy:
    def __init__(self, values):
        self.values = values

    def assess(self, candidate, evidence):
        del evidence
        return self.values[candidate.identifier]


def _audit():
    return {
        "domain_status": [
            {
                "domain": "onchain_crypto_network",
                "monitored": False,
                "decision_certified_and_healthy": False,
                "capability_identifiers": ["manifest:commercial-onchain-intelligence"],
                "historical_capability_present": False,
            },
            {
                "domain": "credit_ratings_defaults",
                "monitored": True,
                "decision_certified_and_healthy": False,
                "capability_identifiers": ["manifest:commercial-ownership-lending"],
                "historical_capability_present": True,
            },
            {
                "domain": "futures_positioning",
                "monitored": True,
                "decision_certified_and_healthy": True,
                "capability_identifiers": ["public:cftc"],
                "historical_capability_present": True,
            },
            {
                "domain": "fund_flows_positioning",
                "monitored": False,
                "decision_certified_and_healthy": False,
                "capability_identifiers": [],
                "historical_capability_present": False,
            },
            {
                "domain": "short_interest_securities_lending",
                "monitored": False,
                "decision_certified_and_healthy": False,
                "capability_identifiers": [],
                "historical_capability_present": False,
            },
            {
                "domain": "insider_institutional_ownership",
                "monitored": True,
                "decision_certified_and_healthy": True,
                "capability_identifiers": ["public:sec"],
                "historical_capability_present": False,
            },
        ]
    }


def test_depth_program_ranks_blocking_and_dollar_value_without_inventing_provider_state(monkeypatch):
    crypto = _readiness(
        "candidate:crypto-wrapper",
        asset_class=CandidateAssetClass.US_ETF,
        economic_class=CandidateAssetClass.CRYPTO,
        missing=(UnderwritingDimension.ONCHAIN, UnderwritingDimension.POSITIONING),
        blocking=(),
        deep_missing=(UnderwritingDimension.ONCHAIN, UnderwritingDimension.POSITIONING),
    )
    credit = _readiness(
        "candidate:bond",
        asset_class=CandidateAssetClass.FIXED_INCOME,
        economic_class=CandidateAssetClass.FIXED_INCOME,
        missing=(UnderwritingDimension.CREDIT,),
        blocking=(UnderwritingDimension.CREDIT,),
        deep_missing=(UnderwritingDimension.CREDIT,),
    )
    values = {
        crypto.candidate_identifier: crypto,
        credit.candidate_identifier: credit,
    }
    monkeypatch.setattr(
        module,
        "CandidateDecisionReadinessPolicy",
        lambda: _Policy(values),
    )
    program = build_decision_information_depth_program(
        candidate_evidence_pairs=(
            (SimpleNamespace(identifier=crypto.candidate_identifier), object()),
            (SimpleNamespace(identifier=credit.candidate_identifier), object()),
        ),
        portfolio_value=250_000.0,
        expected_dollar_opportunity_by_candidate={
            crypto.candidate_identifier: 7_500.0,
            credit.candidate_identifier: 2_000.0,
        },
        information_gap_audit=_audit(),
    )
    assert program.candidate_count == 2
    assert program.demands[0].candidate_identifier == credit.candidate_identifier
    assert program.demands[0].capital_blocking is True
    credit_demand = next(
        item for item in program.demands if item.dimension is UnderwritingDimension.CREDIT
    )
    assert (
        credit_demand.resolution_state
        is InformationDepthResolutionState.EXISTING_MONITORED_NEEDS_CERTIFICATION
    )
    onchain = next(
        item for item in program.demands if item.dimension is UnderwritingDimension.ONCHAIN
    )
    assert onchain.expected_dollar_opportunity_at_stake == pytest.approx(7_500.0)
    assert onchain.deep_economic_gap is True
    assert (
        onchain.resolution_state
        is InformationDepthResolutionState.NEW_OR_PREMIUM_SOURCE_REQUIRED
    )
    assert "manifest:commercial-onchain-intelligence" in onchain.existing_capability_identifiers
    assert program.investment_authority is False
    assert program.execution_authority is False


def test_core_vehicle_gap_is_not_mislabeled_as_research_provider_gap(monkeypatch):
    readiness = _readiness(
        "candidate:vehicle",
        asset_class=CandidateAssetClass.US_ETF,
        economic_class=CandidateAssetClass.US_ETF,
        missing=(UnderwritingDimension.LIQUIDITY,),
        blocking=(UnderwritingDimension.LIQUIDITY,),
        deep_missing=(),
    )
    monkeypatch.setattr(
        module,
        "CandidateDecisionReadinessPolicy",
        lambda: _Policy({readiness.candidate_identifier: readiness}),
    )
    program = build_decision_information_depth_program(
        candidate_evidence_pairs=((SimpleNamespace(identifier=readiness.candidate_identifier), object()),),
        portfolio_value=250_000.0,
        information_gap_audit=_audit(),
    )
    liquidity = next(
        item for item in program.demands if item.dimension is UnderwritingDimension.LIQUIDITY
    )
    assert liquidity.mapped_domains == ()
    assert (
        liquidity.resolution_state
        is InformationDepthResolutionState.CORE_CAPABILITY_STACK_REQUIRED
    )


def test_decision_certified_positioning_source_is_recognized_but_other_positioning_gaps_remain(monkeypatch):
    readiness = _readiness(
        "candidate:commodity",
        asset_class=CandidateAssetClass.COMMODITY,
        economic_class=CandidateAssetClass.COMMODITY,
        missing=(UnderwritingDimension.POSITIONING,),
        blocking=(),
        deep_missing=(UnderwritingDimension.POSITIONING,),
    )
    monkeypatch.setattr(
        module,
        "CandidateDecisionReadinessPolicy",
        lambda: _Policy({readiness.candidate_identifier: readiness}),
    )
    program = build_decision_information_depth_program(
        candidate_evidence_pairs=((SimpleNamespace(identifier=readiness.candidate_identifier), object()),),
        portfolio_value=250_000.0,
        information_gap_audit=_audit(),
    )
    positioning = next(
        item for item in program.demands if item.dimension is UnderwritingDimension.POSITIONING
    )
    assert (
        positioning.resolution_state
        is InformationDepthResolutionState.EXISTING_DECISION_CERTIFIED
    )
    assert "public:cftc" in positioning.existing_capability_identifiers
    assert positioning.investment_authority is False
