"""Forecast calibration, cutoff, lineage, and authority-boundary tests."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from application import (
    CandidateForecastScenarioImpact,
    CandidateForecastSupport,
    ForecastSupportingProductionContextProvider,
    SQLiteCandidateForecastSupportStore,
)
from application.cio_cycle import CandidateCycleContext
from application.production_cio import ProductionContextManifest
from committee.specialists import MacroSpecialistContext, MarketSpecialistContext
from governance import (
    ForecastEvidenceError,
    ForecastScenario,
    GovernedForecastEvidence,
    SQLiteForecastEvidenceStore,
)

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
            ForecastScenario("base", 0.60, "Moderate expansion continues."),
            ForecastScenario("upside", 0.20, "Productivity improves growth."),
            ForecastScenario("downside", 0.20, "Tight conditions weaken demand."),
        ),
        confidence=0.72,
        calibration_method="rolling-origin Brier calibration",
        calibration_sample_size=84,
        historical_accuracy=0.67,
        model_versions=(("global_growth_model", "v3.2"),),
        data_versions=(("macro_vintage", "2026-07-27T11:55Z"),),
        evidence_identifiers=("macro-release:1", "rates-curve:1"),
        originating_fact_identifiers=("origin:gdp:1", "origin:rates:1"),
        limitations=("Annual horizon; tail events remain underrepresented.",),
        invalidation_conditions=("Material revision to growth or inflation.",),
    )


def test_forecast_preserves_required_governance_lineage() -> None:
    forecast = _forecast()
    payload = forecast.to_dict()

    assert payload["horizon_seconds"] == forecast.horizon_seconds
    assert sum(item["probability"] for item in payload["scenarios"]) == 1.0
    assert payload["calibration_method"] == "rolling-origin Brier calibration"
    assert payload["calibration_sample_size"] == 84
    assert payload["historical_accuracy"] == 0.67
    assert payload["model_versions"] == [["global_growth_model", "v3.2"]]
    assert payload["data_versions"] == [["macro_vintage", "2026-07-27T11:55Z"]]
    assert payload["originating_fact_identifiers"] == [
        "origin:gdp:1",
        "origin:rates:1",
    ]
    assert payload["supporting_only"] is True
    assert payload["independent_decision_authority"] is False


def test_forecast_probabilities_and_supporting_only_boundary_fail_closed() -> None:
    valid = _forecast()
    with pytest.raises(ValueError, match="sum to 1"):
        GovernedForecastEvidence(
            identifier="forecast:invalid",
            target=valid.target,
            as_of=valid.as_of,
            knowledge_cutoff=valid.knowledge_cutoff,
            horizon_end=valid.horizon_end,
            generated_at=valid.generated_at,
            scenarios=(
                ForecastScenario("base", 0.70, "Base"),
                ForecastScenario("downside", 0.20, "Downside"),
            ),
            confidence=valid.confidence,
            calibration_method=valid.calibration_method,
            calibration_sample_size=valid.calibration_sample_size,
            historical_accuracy=valid.historical_accuracy,
            model_versions=valid.model_versions,
            data_versions=valid.data_versions,
            evidence_identifiers=valid.evidence_identifiers,
            originating_fact_identifiers=valid.originating_fact_identifiers,
            limitations=valid.limitations,
            invalidation_conditions=valid.invalidation_conditions,
        )

    payload = valid.to_dict()
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
        rationale="Supports the macro specialist evidence.",
        limitations=("Does not create, rank, size, or decide the candidate.",),
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


@dataclass(frozen=True)
class _Context:
    screening_cycle_identifier: str
    knowledge_cutoff: datetime
    manifest: ProductionContextManifest
    specialist_contexts: tuple[CandidateCycleContext, ...] = ()


class _Delegate:
    code_version = "commit:test"

    def __init__(self, context: _Context) -> None:
        self.context = context

    def load_context(self, *, as_of: datetime) -> _Context:
        assert as_of == AS_OF
        return self.context


def _manifest() -> ProductionContextManifest:
    return ProductionContextManifest(
        identifier="context-manifest:1",
        screening_publication_identifier="publication:1",
        portfolio_snapshot_identifier="portfolio:1",
        context_evidence_identifier="context-evidence:1",
        as_of=CUTOFF,
        knowledge_cutoff=CUTOFF,
        candidate_identifiers=("candidate:qualified",),
        candidate_context_identifiers=("candidate-context:qualified",),
        evidence_identifiers=("evidence:base",),
        source_versions=(("source", "v1"),),
        model_versions=(("candidate", "v1"),),
    )


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
    provider = ForecastSupportingProductionContextProvider(
        delegate=_Delegate(_Context("screening:1", CUTOFF, _manifest())),
        forecast_store=forecast_store,
        reference_store=reference_store,
    )

    with pytest.raises(RuntimeError, match="outside the canonical qualified set"):
        provider.load_context(as_of=AS_OF)


def _cycle_context() -> CandidateCycleContext:
    return CandidateCycleContext(
        candidate_identifier="candidate:qualified",
        analysis_completed_at=AS_OF + timedelta(minutes=1),
        macro=MacroSpecialistContext(
            as_of=AS_OF,
            regime="moderate growth",
            expected_return_impact=0.01,
            confidence=0.80,
            tailwinds=("Growth is positive",),
            headwinds=("Policy is restrictive",),
            systemic_risks=("Inflation reaccelerates",),
            scenarios=("Review if growth contracts",),
            evidence_identifiers=("macro:state",),
        ),
        market=MarketSpecialistContext(
            as_of=AS_OF,
            market_regime="constructive",
            expected_return_impact=0.01,
            confidence=0.80,
            trend=0.60,
            momentum=0.55,
            breadth=0.50,
            liquidity=0.75,
            positioning=0.20,
            evidence=("Market technicals are constructive",),
            risks=("Momentum can reverse",),
            entry_conditions=("Trend remains positive",),
            evidence_identifiers=("market:technicals",),
        ),
    )


def _translated_support() -> CandidateForecastSupport:
    return CandidateForecastSupport(
        identifier="forecast-support:candidate:translated",
        screening_cycle_identifier="screening:1",
        candidate_identifier="candidate:qualified",
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
        forecast_identifiers=("forecast:global-growth:1",),
        rationale="Translate calibrated global-growth scenarios into candidate effects.",
        limitations=("Translation remains conditional on the exposure map.",),
        scenario_impacts=(
            CandidateForecastScenarioImpact(
                forecast_identifier="forecast:global-growth:1",
                scenario_name="base",
                candidate_return_impact=0.03,
                expected_path_drawdown=-0.08,
                rationale="Moderate expansion supports diversified equities.",
            ),
            CandidateForecastScenarioImpact(
                forecast_identifier="forecast:global-growth:1",
                scenario_name="upside",
                candidate_return_impact=0.08,
                expected_path_drawdown=-0.05,
                rationale="Productivity upside broadens earnings growth.",
            ),
            CandidateForecastScenarioImpact(
                forecast_identifier="forecast:global-growth:1",
                scenario_name="downside",
                candidate_return_impact=-0.12,
                expected_path_drawdown=-0.25,
                rationale="Demand weakness reduces global equity returns.",
            ),
        ),
        model_agreement=0.72,
        forecast_stability=0.68,
        path_drawdown_probability=0.30,
        cross_asset_signals=("Rates, credit, FX, commodities, and equities agree",),
        contradictory_evidence=("Credit spreads are no longer tightening",),
        review_conditions=("Reassess after material forecast revisions",),
        translation_method="scenario exposure map",
        translation_model_version="v1",
    )


def test_forecast_provider_attaches_separated_specialist_context(tmp_path: Path) -> None:
    forecast_store = SQLiteForecastEvidenceStore(tmp_path / "forecasts.db")
    reference_store = SQLiteCandidateForecastSupportStore(tmp_path / "support.db")
    forecast_store.append(_forecast())
    reference_store.append(_translated_support())
    base = _Context(
        "screening:1",
        CUTOFF,
        _manifest(),
        specialist_contexts=(_cycle_context(),),
    )
    provider = ForecastSupportingProductionContextProvider(
        delegate=_Delegate(base),
        forecast_store=forecast_store,
        reference_store=reference_store,
    )

    context = provider.load_context(as_of=AS_OF)
    forecast = context.specialist_contexts[0].forecast

    assert forecast is not None
    assert forecast.expected_return_impact == pytest.approx(0.01)
    assert forecast.forecast_horizon_days == 365
    assert forecast.model_agreement == pytest.approx(0.72)
    assert "forecast-support:candidate:translated" in (
        context.manifest.evidence_identifiers
    )
    assert ("forecast_candidate_translation", "v1") in (
        context.manifest.model_versions
    )


def test_forecast_specialist_translation_requires_complete_scenario_coverage(
    tmp_path: Path,
) -> None:
    forecast_store = SQLiteForecastEvidenceStore(tmp_path / "forecasts.db")
    reference_store = SQLiteCandidateForecastSupportStore(tmp_path / "support.db")
    forecast_store.append(_forecast())
    incomplete = replace(
        _translated_support(),
        identifier="forecast-support:candidate:incomplete",
        scenario_impacts=_translated_support().scenario_impacts[:-1],
    )
    reference_store.append(incomplete)
    provider = ForecastSupportingProductionContextProvider(
        delegate=_Delegate(
            _Context(
                "screening:1",
                CUTOFF,
                _manifest(),
                specialist_contexts=(_cycle_context(),),
            )
        ),
        forecast_store=forecast_store,
        reference_store=reference_store,
    )

    with pytest.raises(RuntimeError, match="cover every referenced scenario"):
        provider.load_context(as_of=AS_OF)
