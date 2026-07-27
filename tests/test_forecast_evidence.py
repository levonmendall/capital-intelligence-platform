"""Forecast evidence, calibration, cutoff, and authority-boundary tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from application import (
    CandidateForecastSupport,
    ForecastSupportingProductionContextProvider,
    SQLiteCandidateForecastSupportStore,
)
from application.production_cio import ProductionContextManifest
from application.production_context_contract import ProductionCanonicalCIOContext
from committee import SpecialistContext
from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    OpportunityEngineContext,
)
from governance import (
    ForecastEvidenceError,
    ForecastScenario,
    GovernedForecastEvidence,
    SQLiteForecastEvidenceStore,
)
from portfolio import CanonicalPortfolioSnapshot

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CUTOFF = AS_OF - timedelta(minutes=5)


def _forecast(
    *,
    identifier: str = "forecast:global-growth:1",
    generated_at: datetime = CUTOFF,
) -> GovernedForecastEvidence:
    return GovernedForecastEvidence(
        identifier=identifier,
        target="global real GDP growth",
        as_of=CUTOFF - timedelta(hours=1),
        knowledge_cutoff=CUTOFF,
        horizon_end=AS_OF + timedelta(days=365),
        generated_at=generated_at,
        scenarios=(
            ForecastScenario(
                name="base",
                probability=0.60,
                description="Moderate expansion continues.",
            ),
            ForecastScenario(
                name="upside",
                probability=0.20,
                description="Productivity and disinflation improve growth.",
            ),
            ForecastScenario(
                name="downside",
                probability=0.20,
                description="Tight financial conditions weaken demand.",
            ),
        ),
        confidence=0.72,
        calibration_method="rolling-origin Brier calibration",
        calibration_sample_size=84,
        historical_accuracy=0.67,
        model_versions=(("global_growth_model", "v3.2"),),
        data_versions=(("macro_vintage", "2026-07-27T11:55Z"),),
        evidence_identifiers=("macro-release:1", "rates-curve:1"),
        originating_fact_identifiers=("origin:gdp:1", "origin:rates:1"),
        limitations=("annual horizon; tail events remain underrepresented",),
        invalidation_conditions=("material revision to the growth or inflation path",),
    )


def test_forecast_preserves_horizon_calibration_versions_and_lineage() -> None:
    forecast = _forecast()
    payload = forecast.to_dict()

    assert payload["horizon_seconds"] == forecast.horizon_seconds
    assert sum(item["probability"] for item in payload["scenarios"]) == 1.0
    assert payload["calibration_method"] == "rolling-origin Brier calibration"
    assert payload["calibration_sample_size"] == 84
    assert payload["historical_accuracy"] == 0.67
    assert payload["model_versions"] == [["global_growth_model", "v3.2"]]
    assert payload["data_versions"] == [
        ["macro_vintage", "2026-07-27T11:55Z"]
    ]
    assert payload["originating_fact_identifiers"] == [
        "origin:gdp:1",
        "origin:rates:1",
    ]
    assert payload["supporting_only"] is True
    assert payload["independent_decision_authority"] is False


def test_forecast_probability_and_supporting_authority_fail_closed() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        GovernedForecastEvidence(
            **{
                **_forecast().to_dict(),
                "as_of": _forecast().as_of,
                "knowledge_cutoff": _forecast().knowledge_cutoff,
                "horizon_end": _forecast().horizon_end,
                "generated_at": _forecast().generated_at,
                "scenarios": (
                    ForecastScenario("base", 0.7, "Base"),
                    ForecastScenario("downside", 0.2, "Downside"),
                ),
                "model_versions": (("model", "v1"),),
                "data_versions": (("data", "v1"),),
                "evidence_identifiers": ("evidence:1",),
                "originating_fact_identifiers": ("origin:1",),
                "limitations": ("limitation",),
                "invalidation_conditions": ("condition",),
            }
        )

    payload = _forecast().to_dict()
    payload["supporting_only"] = False
    with pytest.raises(ValueError, match="supporting-only"):
        GovernedForecastEvidence.from_dict(payload)


def test_future_known_forecast_cannot_support_a_decision() -> None:
    forecast = _forecast(generated_at=AS_OF + timedelta(seconds=1))

    with pytest.raises(ForecastEvidenceError, match="after the decision"):
        forecast.require_usable(
            decision_timestamp=AS_OF,
            knowledge_cutoff=CUTOFF,
        )


def test_forecast_and_candidate_reference_stores_are_append_only(tmp_path: Path) -> None:
    forecast_store = SQLiteForecastEvidenceStore(tmp_path / "forecasts.db")
    support_store = SQLiteCandidateForecastSupportStore(tmp_path / "support.db")
    forecast = _forecast()
    reference = CandidateForecastSupport(
        identifier="forecast-support:candidate:1",
        screening_cycle_identifier="screening:1",
        candidate_identifier="candidate:1",
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
        forecast_identifiers=(forecast.identifier,),
        rationale="Scenario distribution informs the macro specialist evidence.",
        limitations=("Does not create or rank the candidate.",),
    )

    assert forecast_store.append(forecast) == 1
    assert forecast_store.append(forecast) == 1
    assert support_store.append(reference) == 1
    assert support_store.append(reference) == 1
    assert forecast_store.verify_integrity()
    assert support_store.verify_integrity()

    with sqlite3.connect(forecast_store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM governed_forecast_evidence")
    with sqlite3.connect(support_store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE candidate_forecast_support_events SET payload_json='{}'")


def test_forecast_reference_cannot_name_an_unqualified_candidate(tmp_path: Path) -> None:
    forecast_store = SQLiteForecastEvidenceStore(tmp_path / "forecasts.db")
    reference_store = SQLiteCandidateForecastSupportStore(tmp_path / "support.db")
    forecast_store.append(_forecast())
    reference_store.append(
        CandidateForecastSupport(
            identifier="support:unknown",
            screening_cycle_identifier="screening:1",
            candidate_identifier="candidate:unknown",
            as_of=AS_OF,
            knowledge_cutoff=CUTOFF,
            forecast_identifiers=("forecast:global-growth:1",),
            rationale="Supporting macro evidence.",
            limitations=("No candidate authority.",),
        )
    )

    class Delegate:
        code_version = "commit:test"

        def load_context(self, *, as_of):
            instrument = CandidateInstrument(
                instrument_id="instrument:1",
                symbol="AAPL",
                name="Apple",
                asset_class=CandidateAssetClass.US_EQUITY,
                venue="NASDAQ",
                country_code="US",
                average_daily_dollar_volume=1_000_000_000,
                data_age_hours=1,
                analytical_coverage=1,
                security_master_snapshot_identifier="security-master:1",
                security_master_record_identifiers=("record:1",),
            )
            candidate = CandidateDecisionRecord(
                identifier="candidate:qualified",
                instrument=instrument,
                as_of=as_of,
                expected_return=0.10,
                downside_risk=0.05,
                confidence=0.8,
                liquidity_score=0.9,
                implementation_cost_return=0.001,
                evidence_identifiers=("evidence:base",),
                model_versions=(("candidate", "v1"),),
            )
            manifest = ProductionContextManifest(
                context_identifier="context:1",
                screening_cycle_identifier="screening:1",
                screening_publication_identifier="publication:1",
                portfolio_snapshot_identifier="portfolio:1",
                candidate_identifiers=(candidate.identifier,),
                evidence_identifiers=("evidence:base",),
                source_versions=(("source", "v1"),),
                model_versions=(("candidate", "v1"),),
                code_version="commit:test",
                knowledge_cutoff=CUTOFF,
            )
            return ProductionCanonicalCIOContext(
                identifier="context:1",
                screening_cycle_identifier="screening:1",
                opportunity_context=OpportunityEngineContext(
                    as_of=as_of,
                    candidates=(candidate,),
                    current_holding_symbols=(),
                    cash_return=0.04,
                    minimum_expected_return=0.05,
                    minimum_liquidity_score=0.5,
                    maximum_implementation_cost_return=0.01,
                    maximum_downside_risk=0.3,
                    minimum_confidence=0.5,
                ),
                specialist_contexts=tuple(
                    SpecialistContext(
                        candidate=candidate,
                        portfolio=CanonicalPortfolioSnapshot(
                            identifier="portfolio:1",
                            portfolio_code="COMPOUNDING",
                            display_name="Compounding",
                            constraint_profile="institutional",
                            as_of=as_of,
                            starting_capital=100_000,
                            cash_amount=100_000,
                            positions=(),
                        ),
                        evidence_summary="Evidence",
                        risk_summary="Risk",
                    )
                    for _ in range(5)
                ),
                portfolio=CanonicalPortfolioSnapshot(
                    identifier="portfolio:1",
                    portfolio_code="COMPOUNDING",
                    display_name="Compounding",
                    constraint_profile="institutional",
                    as_of=as_of,
                    starting_capital=100_000,
                    cash_amount=100_000,
                    positions=(),
                ),
                code_version="commit:test",
                manifest=manifest,
                knowledge_cutoff=CUTOFF,
                process_version="process:test",
                eligible_universe_publication_identifier="universe:1",
            )

    provider = ForecastSupportingProductionContextProvider(
        delegate=Delegate(),
        forecast_store=forecast_store,
        reference_store=reference_store,
    )
    with pytest.raises(RuntimeError, match="outside the canonical qualified set"):
        provider.load_context(as_of=AS_OF)
