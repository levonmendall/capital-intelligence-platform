from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from providers.render_public_provider_validation import (
    build_render_public_provider_validation,
)

AS_OF = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Definition:
    identifier: str
    credential_environment_variables: tuple[str, ...]


@dataclass(frozen=True)
class _SourceResult:
    source_identifier: str
    succeeded: bool
    record_count: int
    error: str | None = None


@dataclass(frozen=True)
class _Catalog:
    sources: tuple[_Definition, ...]


@dataclass(frozen=True)
class _Coverage:
    sources: tuple[_SourceResult, ...]


def _supplemental(provider: str) -> dict[str, object]:
    variable = {
        "openfigi": "OPENFIGI_API_KEY",
        "alpha-vantage": "ALPHA_VANTAGE_API_KEY",
        "twelve-data": "TWELVE_DATA_API_KEY",
    }[provider]
    return {
        "configured": True,
        "credential_names": [variable],
        "selected_credential": variable,
        "passed": True,
        "evidence": {"probe": provider, "authenticated": True},
    }


def test_all_eight_render_credentials_are_reported_without_secret_values(
    monkeypatch,
) -> None:
    variables = (
        "OPENFIGI_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "TWELVE_DATA_API_KEY",
        "BEA_API_KEY",
        "CENSUS_API_KEY",
        "USDA_NASS_API_KEY",
        "EIA_API_KEY",
        "NASA_FIRMS_MAP_KEY",
    )
    for index, name in enumerate(variables, start=1):
        monkeypatch.setenv(name, f"secret-value-{index}")
    public_variables = variables[3:]
    catalog = _Catalog(
        sources=tuple(
            _Definition(
                identifier=f"source:{name.lower()}",
                credential_environment_variables=(name,),
            )
            for name in public_variables
        )
    )
    coverage = _Coverage(
        sources=tuple(
            _SourceResult(
                source_identifier=f"source:{name.lower()}",
                succeeded=True,
                record_count=1,
            )
            for name in public_variables
        )
    )

    report = build_render_public_provider_validation(
        catalog=catalog,
        coverage_report=coverage,
        evaluated_at=AS_OF,
        supplemental_results={
            name: _supplemental(name)
            for name in ("openfigi", "alpha-vantage", "twelve-data")
        },
    )

    assert report["state"] == "validated"
    assert report["provider_count"] == 8
    assert report["configured_provider_count"] == 8
    assert report["validated_provider_count"] == 8
    assert report["secret_values_disclosed"] is False
    assert report["provider_certification_granted"] is False
    assert report["data_readiness_granted"] is False
    encoded = str(report)
    assert "secret-value" not in encoded
    assert all(item["state"] == "validated" for item in report["providers"])


def test_configured_but_failed_source_is_degraded_not_certified(monkeypatch) -> None:
    monkeypatch.setenv("BEA_API_KEY", "private-bea-value")
    report = build_render_public_provider_validation(
        catalog=_Catalog(
            sources=(
                _Definition(
                    identifier="source:bea",
                    credential_environment_variables=("BEA_API_KEY",),
                ),
            )
        ),
        coverage_report=_Coverage(
            sources=(
                _SourceResult(
                    source_identifier="source:bea",
                    succeeded=False,
                    record_count=0,
                    error="BEA returned HTTP 401",
                ),
            )
        ),
        evaluated_at=AS_OF,
        supplemental_results={
            name: {
                "configured": False,
                "credential_names": [],
                "selected_credential": None,
                "passed": False,
                "evidence": {},
                "error": "not configured",
            }
            for name in ("openfigi", "alpha-vantage", "twelve-data")
        },
    )

    bea = next(item for item in report["providers"] if item["provider"] == "bea")
    assert bea["configured"] is True
    assert bea["authentication_validated"] is False
    assert bea["state"] == "validation_failed"
    assert report["state"] == "blocked"
    assert report["provider_certification_granted"] is False
    assert "private-bea-value" not in str(report)
