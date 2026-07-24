"""Tests for the mobile-first CIO decision card."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

from committee import RegimeGovernanceWorkflow
from monitoring import (
    AlertLevel,
    PortfolioImpactDirection,
    RegimeMaterialChangeEngine,
)
from portfolio import (
    PortfolioFitGate,
    PortfolioFitOutcome,
)
from reporting import (
    build_cio_decision_card,
    decision_card_to_dict,
    render_decision_card_html,
    render_decision_card_json,
    render_decision_card_markdown,
)
from tests.test_material_change_monitoring import (
    ChangedRegimeProvider,
    FIRST_AS_OF,
    SECOND_AS_OF,
    _decision,
    _run,
)
from tests.test_portfolio_fit_gate import (
    _mandate,
    _portfolio,
    _proposal,
)
from run_regime import render_card


def test_approved_decision_becomes_simple_portfolio_card() -> None:
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    decision = _decision(run)

    card = build_cio_decision_card(run, decision)

    assert card.headline == "Portfolio action approved"
    assert card.decision == (
        "Consider holding more diversified risk assets."
    )
    assert card.regime == "Goldilocks"
    assert card.evidence_confidence == 0.79
    assert card.data_status == "Complete"
    assert card.committee_outcome == "Approved"
    assert (
        card.portfolio_direction
        is PortfolioImpactDirection.INCREASE_RISK
    )
    assert card.affected_exposures == (
        "diversified risk assets",
    )
    assert len(card.key_evidence) <= 3
    assert len(card.key_risks) <= 3
    assert len(card.watch_conditions) <= 3
    assert not card.should_alert


def test_no_action_card_keeps_portfolio_still_and_sets_review() -> None:
    run = _run(
        ChangedRegimeProvider(
            unavailable={"WALCL", "STLFSI4"}
        ),
        as_of=FIRST_AS_OF,
    )
    decision = RegimeGovernanceWorkflow(
        clock=lambda: FIRST_AS_OF
    ).evaluate(run)

    card = build_cio_decision_card(run, decision)

    assert card.headline == "No portfolio change"
    assert card.decision == "Keep the portfolio unchanged."
    assert card.data_status == "Limited"
    assert card.committee_outcome == "No action"
    assert card.portfolio_direction is PortfolioImpactDirection.HOLD
    assert card.review_at is not None
    assert "not strong enough" in card.why_now


def test_material_change_controls_alert_and_portfolio_language() -> None:
    previous = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    current = _run(
        ChangedRegimeProvider(
            growth_value=95.0,
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )
    previous_decision = _decision(previous)
    current_decision = _decision(current)
    change = RegimeMaterialChangeEngine(
        clock=lambda: SECOND_AS_OF
    ).compare(
        previous,
        current,
        previous_decision,
        current_decision,
    )

    card = build_cio_decision_card(
        current,
        current_decision,
        change=change,
    )

    assert card.headline == "Risk review is urgent"
    assert card.alert_level is AlertLevel.URGENT
    assert card.should_alert
    assert (
        card.portfolio_direction
        is PortfolioImpactDirection.REDUCE_RISK
    )
    assert "equities" in card.affected_exposures
    assert "crypto risk budget" in card.affected_exposures
    assert card.why_now == change.explanation


def test_json_renderer_is_stable_and_schema_versioned() -> None:
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    card = build_cio_decision_card(run, _decision(run))

    payload = decision_card_to_dict(card)
    rendered = render_decision_card_json(card)

    assert json.loads(rendered) == payload
    assert payload["schema_version"] == "cio-decision-card.v1"
    assert payload["portfolio"]["direction"] == "increase_risk"
    assert payload["should_alert"] is False
    assert render_decision_card_json(card) == rendered


def test_markdown_keeps_primary_decision_above_details() -> None:
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    card = build_cio_decision_card(run, _decision(run))

    rendered = render_decision_card_markdown(card)

    assert rendered.startswith("# Portfolio action approved\n")
    assert rendered.index(card.decision) < rendered.index("<details>")
    assert rendered.index("**Portfolio:**") < rendered.index(
        "<details>"
    )
    assert "## Evidence" in rendered
    assert "## Risks" in rendered
    assert "## Review when" in rendered


def test_html_is_mobile_ready_accessible_and_escapes_content() -> None:
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    card = build_cio_decision_card(run, _decision(run))
    unsafe = replace(
        card,
        headline="<script>alert('x')</script>",
    )

    rendered = render_decision_card_html(unsafe)

    assert '<meta name="viewport"' in rendered
    assert 'aria-label="Portfolio impact"' in rendered
    assert "<details>" in rendered
    assert "<script>alert('x')</script>" not in rendered
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in rendered
    assert "@media (max-width: 430px)" in rendered


def test_canonical_command_renderer_supports_all_card_formats() -> None:
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    decision = _decision(run)

    assert render_card(
        run,
        decision,
        output_format="markdown",
    ).startswith("# Portfolio action approved")
    assert json.loads(
        render_card(
            run,
            decision,
            output_format="json",
        )
    )["schema_version"] == "cio-decision-card.v1"
    assert render_card(
        run,
        decision,
        output_format="html",
    ).startswith("<!doctype html>")


def test_card_makes_smaller_fit_the_primary_portfolio_answer() -> None:
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    decision = _decision(run)
    fit = PortfolioFitGate(
        clock=lambda: FIRST_AS_OF
    ).evaluate(
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

    card = build_cio_decision_card(
        run,
        decision,
        portfolio_fit=fit,
    )
    payload = decision_card_to_dict(card)

    assert fit.outcome is PortfolioFitOutcome.FIT_SMALLER
    assert card.headline == "Use a smaller portfolio change"
    assert card.decision == (
        "Limit the change to 5.0% of the portfolio."
    )
    assert (
        card.portfolio_direction
        is PortfolioImpactDirection.INCREASE_RISK
    )
    assert payload["portfolio"]["fit"]["outcome"] == "fit_smaller"
    assert payload["portfolio"]["fit"][
        "permitted_weight_delta"
    ] == 0.05


def test_card_keeps_portfolio_still_when_risk_budget_is_full() -> None:
    run = _run(
        ChangedRegimeProvider(),
        as_of=FIRST_AS_OF,
    )
    decision = _decision(run)
    fit = PortfolioFitGate(
        clock=lambda: FIRST_AS_OF
    ).evaluate(
        decision,
        _proposal(decision),
        _portfolio(risk_budget_used=0.90),
        _mandate(),
    )

    card = build_cio_decision_card(
        run,
        decision,
        portfolio_fit=fit,
    )

    assert fit.outcome is PortfolioFitOutcome.NO_RISK_BUDGET
    assert card.headline == "No room for more portfolio risk"
    assert card.decision == "Keep the portfolio unchanged."
    assert card.portfolio_direction is PortfolioImpactDirection.HOLD
