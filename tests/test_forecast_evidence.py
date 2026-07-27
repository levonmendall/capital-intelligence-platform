"""Forecast calibration, cutoff, lineage, and authority-boundary tests."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from application import (
    CandidateForecastSupport,
    ForecastSupportingProductionContextProvider,
    SQLiteCandidateForecastSupportStore,
)
from application.production_cio import ProductionContextManifest
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


class _Delegate:
    code_version = "commit:test"

    def __init__(self, context: _Context) -> None:
        self.context = context

    def load_context(self, *, as_of: datetime) -> _Context:
        assert as_of == AS_OF
        return self.context


def _manifest() -> ProductionContextManifest:
    return ProductionContextManifest(
        context_identifier="context:1",
        screening_cycle_identifier="screening:1",
        screening_publication_identifier="publication:1",
        portfolio_snapshot_identifier="portfolio:1",
        candidate_identifiers=("candidate:qualified",),
        evidence_identifiers=("evidence:base",),
        source_versions=(("source", "v1"),),
        model_versions=(("candidate", "v1"),),
        code_version="commit:test",
        knowledge_cutoff=CUTOFF,
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
