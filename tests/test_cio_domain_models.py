from datetime import datetime, timezone

import pytest

from intelligence.cio_guidance import (
    ChangeCondition,
    CIOGuidance,
    ConfidenceScores,
    ScenarioProbability,
)
from intelligence.metadata import (
    DocumentMetadata,
    DocumentStatus,
)
from portfolio_managers.response import MandateID


def build_guidance() -> CIOGuidance:
    return CIOGuidance(
        current_environment="Late-cycle expansion",
        forward_outlook="Slowing growth with a probable soft landing",
        strategic_guidance=(
            "Maintain diversified exposure while modestly reducing "
            "cyclical risk."
        ),
        executive_summary=(
            "Growth is slowing, but recession is not the base case."
        ),
        probability_distribution=[
            ScenarioProbability(
                scenario="Soft landing",
                probability=0.55,
                horizon_months=12,
            ),
            ScenarioProbability(
                scenario="Recession",
                probability=0.25,
                horizon_months=12,
            ),
            ScenarioProbability(
                scenario="Reacceleration",
                probability=0.20,
                horizon_months=12,
            ),
        ],
        confidence=ConfidenceScores(
            data_confidence=0.90,
            forecast_confidence=0.70,
            portfolio_conviction=0.60,
            risk_confidence=0.80,
        ),
        change_my_mind_if=[
            ChangeCondition(
                description=(
                    "Credit spreads widen by at least 150 basis points"
                ),
                indicator="high_yield_spread_change_bps",
                comparison=">=",
                threshold=150.0,
                severity="reverse",
            )
        ],
    )


def test_document_metadata_defaults() -> None:
    metadata = DocumentMetadata()

    assert metadata.version == 1
    assert metadata.status == DocumentStatus.DRAFT
    assert metadata.document_id
    assert metadata.created_at.tzinfo is not None


def test_document_metadata_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        DocumentMetadata(
            created_at=datetime(2026, 7, 22),
        )


def test_scenario_probabilities_must_total_one() -> None:
    with pytest.raises(ValueError):
        CIOGuidance(
            current_environment="Expansion",
            forward_outlook="Continued expansion",
            strategic_guidance="Maintain risk exposure",
            executive_summary="Base case remains constructive.",
            probability_distribution=[
                ScenarioProbability(
                    scenario="Expansion",
                    probability=0.60,
                    horizon_months=12,
                ),
                ScenarioProbability(
                    scenario="Recession",
                    probability=0.20,
                    horizon_months=12,
                ),
            ],
            confidence=ConfidenceScores(
                data_confidence=0.90,
                forecast_confidence=0.70,
                portfolio_conviction=0.60,
                risk_confidence=0.80,
            ),
        )


def test_guidance_returns_highest_probability_scenario() -> None:
    guidance = build_guidance()

    result = guidance.highest_probability_scenario()

    assert result.scenario == "Soft landing"
    assert result.probability == 0.55


def test_only_compounding_mandate_is_active() -> None:
    assert {mandate.value for mandate in MandateID} == {"compounding"}


def test_timezone_aware_metadata_is_accepted() -> None:
    metadata = DocumentMetadata(
        created_at=datetime.now(timezone.utc),
    )

    assert metadata.created_at.tzinfo is not None
