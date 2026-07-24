"""Tests for mandate-aware portfolio-fit governance."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from committee import (
    RegimeGovernanceOutcome,
    RegimeGovernanceWorkflow,
)
from portfolio import (
    AssetBucket,
    AssetBucketLimit,
    PortfolioFitGate,
    PortfolioFitOutcome,
    PortfolioMandate,
    PortfolioPosition,
    PortfolioProposal,
    PortfolioSnapshot,
)
from journal import JournalEventType, SQLiteAppendOnlyJournal
from tests.test_material_change_monitoring import (
    ChangedRegimeProvider,
    FIRST_AS_OF,
    SECOND_AS_OF,
    _decision,
    _run,
)


def _portfolio(
    *,
    risk_budget_used: float = 0.65,
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        identifier="balanced-portfolio",
        as_of=FIRST_AS_OF,
        nav=100_000,
        cash_weight=0.30,
        risk_budget_used=risk_budget_used,
        positions=(
            PortfolioPosition(
                identifier="SPY",
                bucket=AssetBucket.EQUITY,
                weight=0.35,
                risk_budget_usage=0.35,
                liquidity_score=1.0,
                exposure_tags=(
                    "equity_beta",
                    "risk_assets",
                ),
            ),
            PortfolioPosition(
                identifier="AGG",
                bucket=AssetBucket.FIXED_INCOME,
                weight=0.30,
                risk_budget_usage=0.15,
                liquidity_score=1.0,
                exposure_tags=("duration",),
            ),
            PortfolioPosition(
                identifier="BTC",
                bucket=AssetBucket.CRYPTO,
                weight=0.05,
                risk_budget_usage=0.15,
                liquidity_score=0.90,
                exposure_tags=(
                    "crypto_beta",
                    "risk_assets",
                ),
            ),
        ),
    )


def _mandate(
    *,
    prohibited_identifiers: tuple[str, ...] = (),
) -> PortfolioMandate:
    return PortfolioMandate(
        identifier="balanced-mandate",
        version="balanced.v1",
        maximum_position_weight=0.40,
        minimum_cash_weight=0.10,
        maximum_risk_budget=0.90,
        minimum_liquidity_score=0.60,
        bucket_limits=(
            AssetBucketLimit(
                AssetBucket.EQUITY,
                0.65,
            ),
            AssetBucketLimit(
                AssetBucket.FIXED_INCOME,
                0.50,
            ),
            AssetBucketLimit(
                AssetBucket.CRYPTO,
                0.10,
            ),
        ),
        prohibited_identifiers=prohibited_identifiers,
        prohibited_exposure_tags=("leveraged_token",),
    )


def _approved_decision():
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    return _decision(run)


def _proposal(
    decision,
    *,
    identifier: str = "proposal-quality",
    target: str = "QUALITY",
    bucket: AssetBucket = AssetBucket.EQUITY,
    weight_delta: float = 0.05,
    risk_delta: float = 0.05,
    liquidity: float = 0.95,
    tags: tuple[str, ...] = ("quality_equity",),
) -> PortfolioProposal:
    return PortfolioProposal(
        identifier=identifier,
        source_decision_identifier=(
            decision.decision_identifier
        ),
        target_identifier=target,
        bucket=bucket,
        requested_weight_delta=weight_delta,
        estimated_risk_budget_delta=risk_delta,
        liquidity_score=liquidity,
        exposure_tags=tags,
    )


def _gate():
    return PortfolioFitGate(clock=lambda: FIRST_AS_OF)


def test_proposal_fits_within_mandate_and_risk_limits() -> None:
    decision = _approved_decision()

    result = _gate().evaluate(
        decision,
        _proposal(decision),
        _portfolio(),
        _mandate(),
    )

    assert result.outcome is PortfolioFitOutcome.FIT
    assert result.permits_expression
    assert result.permitted_weight_delta == 0.05
    assert result.permitted_risk_budget_delta == 0.05
    assert result.binding_constraints == ()
    assert result.headline == "The proposal fits the portfolio"


def test_position_limit_reduces_permitted_size() -> None:
    decision = _approved_decision()

    result = _gate().evaluate(
        decision,
        _proposal(
            decision,
            target="SPY",
            weight_delta=0.10,
            risk_delta=0.10,
            tags=("large_cap_equity",),
        ),
        _portfolio(),
        _mandate(),
    )

    assert result.outcome is PortfolioFitOutcome.FIT_SMALLER
    assert result.permits_expression
    assert result.permitted_weight_delta == 0.05
    assert result.permitted_risk_budget_delta == 0.05
    assert result.binding_constraints == ("position_limit",)
    assert result.headline == "Use a smaller portfolio change"


def test_overlap_requests_replacement_instead_of_more_risk() -> None:
    decision = _approved_decision()

    result = _gate().evaluate(
        decision,
        _proposal(
            decision,
            target="QQQ",
            tags=("equity_beta",),
        ),
        _portfolio(),
        _mandate(),
    )

    assert result.outcome is PortfolioFitOutcome.REPLACE_OVERLAP
    assert not result.permits_expression
    assert result.overlapping_positions == ("SPY",)
    assert result.permitted_weight_delta is None
    assert "similar risk" in result.explanation


def test_full_risk_budget_blocks_new_addition() -> None:
    decision = _approved_decision()

    result = _gate().evaluate(
        decision,
        _proposal(decision),
        _portfolio(risk_budget_used=0.90),
        _mandate(),
    )

    assert result.outcome is PortfolioFitOutcome.NO_RISK_BUDGET
    assert not result.permits_expression
    assert "risk_budget" in result.binding_constraints
    assert result.headline == "No room for more portfolio risk"


def test_mandate_blocks_prohibited_or_illiquid_additions() -> None:
    decision = _approved_decision()

    prohibited = _gate().evaluate(
        decision,
        _proposal(decision, target="BLOCKED"),
        _portfolio(),
        _mandate(prohibited_identifiers=("BLOCKED",)),
    )
    illiquid = _gate().evaluate(
        decision,
        _proposal(
            decision,
            identifier="proposal-illiquid",
            liquidity=0.30,
        ),
        _portfolio(),
        _mandate(),
    )

    assert prohibited.outcome is PortfolioFitOutcome.POLICY_BLOCKED
    assert prohibited.binding_constraints == (
        "prohibited_identifier",
    )
    assert illiquid.outcome is PortfolioFitOutcome.POLICY_BLOCKED
    assert illiquid.binding_constraints == ("liquidity",)


def test_unapproved_committee_decision_cannot_reach_portfolio() -> None:
    run = _run(
        ChangedRegimeProvider(
            unavailable={"WALCL", "STLFSI4"}
        ),
        as_of=FIRST_AS_OF,
    )
    decision = RegimeGovernanceWorkflow(
        clock=lambda: FIRST_AS_OF
    ).evaluate(run)

    result = _gate().evaluate(
        decision,
        _proposal(decision),
        _portfolio(),
        _mandate(),
    )

    assert result.outcome is PortfolioFitOutcome.NO_ACTION
    assert not result.permits_expression
    assert result.binding_constraints == (
        "committee_approval",
    )


def test_proposal_direction_must_match_committee_action() -> None:
    decision = _approved_decision()

    result = _gate().evaluate(
        decision,
        _proposal(
            decision,
            weight_delta=-0.05,
            risk_delta=-0.05,
        ),
        _portfolio(),
        _mandate(),
    )

    assert result.outcome is PortfolioFitOutcome.POLICY_BLOCKED
    assert result.binding_constraints == (
        "recommendation_direction",
    )


def test_risk_reduction_is_permitted_without_new_capacity() -> None:
    run = _run(
        ChangedRegimeProvider(
            growth_value=95.0,
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )
    decision = replace(
        _decision(run),
        outcome=RegimeGovernanceOutcome.APPROVE,
        rationale="Risk reduction approved for fit-gate test.",
    )
    proposal = _proposal(
        decision,
        target="SPY",
        weight_delta=-0.10,
        risk_delta=-0.10,
        tags=("equity_beta",),
    )

    result = PortfolioFitGate(
        clock=lambda: SECOND_AS_OF
    ).evaluate(
        decision,
        proposal,
        _portfolio(risk_budget_used=0.90),
        _mandate(prohibited_identifiers=("SPY",)),
    )

    assert result.outcome is PortfolioFitOutcome.FIT
    assert result.permits_expression
    assert result.permitted_weight_delta == -0.10
    assert result.permitted_risk_budget_delta == -0.10
    assert "lowers portfolio" in result.explanation


def test_reduction_cannot_exceed_current_position() -> None:
    run = _run(
        ChangedRegimeProvider(
            growth_value=95.0,
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )
    decision = replace(
        _decision(run),
        outcome=RegimeGovernanceOutcome.APPROVE,
        rationale="Risk reduction approved for fit-gate test.",
    )

    result = PortfolioFitGate(
        clock=lambda: SECOND_AS_OF
    ).evaluate(
        decision,
        _proposal(
            decision,
            target="BTC",
            bucket=AssetBucket.CRYPTO,
            weight_delta=-0.10,
            risk_delta=-0.20,
            tags=("crypto_beta",),
        ),
        _portfolio(),
        _mandate(),
    )

    assert result.outcome is PortfolioFitOutcome.FIT_SMALLER
    assert result.permitted_weight_delta == -0.05
    assert result.permitted_risk_budget_delta == -0.10
    assert result.binding_constraints == ("current_position",)


def test_fit_decision_is_preserved_without_executing_it(
    tmp_path,
) -> None:
    decision = _approved_decision()
    result = _gate().evaluate(
        decision,
        _proposal(decision),
        _portfolio(),
        _mandate(),
    )
    journal = SQLiteAppendOnlyJournal(
        tmp_path / "fit.db",
        clock=lambda: FIRST_AS_OF,
        identifier_factory=lambda: "fit-event",
    )

    event = journal.append_portfolio_fit_decision(result)

    assert event.event_type is (
        JournalEventType.PORTFOLIO_FIT_DECISION
    )
    assert event.aggregate_identifier == (
        "portfolio:balanced-portfolio"
    )
    assert event.payload["outcome"] == "fit"
    assert event.payload["permits_expression"] is True
    assert event.payload["permitted_weight_delta"] == 0.05
    assert journal.verify_integrity()


def test_cash_is_reserved_for_funding_not_a_proposal_bucket() -> None:
    decision = _approved_decision()

    with pytest.raises(
        ValueError,
        match="cash is the funding reserve",
    ):
        _proposal(
            decision,
            bucket=AssetBucket.CASH,
        )
