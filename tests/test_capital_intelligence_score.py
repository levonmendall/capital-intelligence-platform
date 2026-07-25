"""Tests for the daily Capital Intelligence Score."""

from __future__ import annotations

import json

from reporting import (
    build_capital_intelligence_score,
    capital_intelligence_score_to_dict,
    render_capital_intelligence_score_json,
    render_capital_intelligence_score_markdown,
)
from tests.test_material_change_monitoring import (
    ChangedRegimeProvider,
    FIRST_AS_OF,
    _decision,
    _run,
)


def test_daily_score_matches_the_primary_product_identity() -> None:
    run = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    score = build_capital_intelligence_score(run, _decision(run))

    assert score.score == 82
    assert score.label == "Strong"
    assert score.environment == "Constructive"
    assert score.risk == "Moderate"
    assert score.committee == "6–0 Favor Risk Assets"
    assert "more diversified risk assets" in score.portfolio_impact


def test_score_falls_when_evidence_gate_blocks_committee_action() -> None:
    run = _run(
        ChangedRegimeProvider(unavailable={"WALCL", "STLFSI4"}),
        as_of=FIRST_AS_OF,
    )
    score = build_capital_intelligence_score(run, _decision(run))

    assert score.score < 50
    assert score.label == "Limited"
    assert score.committee.startswith("No vote")
    assert score.portfolio_impact == "Keep the portfolio unchanged."


def test_score_renderers_are_schema_versioned_and_explainable() -> None:
    run = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    score = build_capital_intelligence_score(run, _decision(run))

    payload = capital_intelligence_score_to_dict(score)
    assert payload["schema_version"] == "capital-intelligence-score.v1"
    assert payload["components"]["committee_support"] == 1.0
    assert json.loads(render_capital_intelligence_score_json(score)) == payload

    markdown = render_capital_intelligence_score_markdown(score)
    assert markdown.startswith("# Today's Capital Intelligence\n\n## 82")
    assert "**Committee:** 6–0 Favor Risk Assets" in markdown
