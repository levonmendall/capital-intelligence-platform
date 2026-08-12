from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.derivative_market import ExerciseStyle, OptionQuoteRecord, OptionRight
from providers.free_derivative_risk import (
    CmeSpanRiskProvider,
    DerivedVolatilitySurfaceProvider,
    FreeDerivativeRiskError,
    OccOfraRiskProvider,
    preflight_free_derivative_risk_resources,
)


AS_OF = datetime(2026, 8, 11, 22, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200
    content = b"OCC OFRA PUBLIC RISK ARRAY DATA\n" * 8


def test_cme_span_local_binding_is_hashed_without_inventing_margin(tmp_path) -> None:
    source = tmp_path / "cme-span.pa2"
    source.write_bytes(b"CME SPAN 2 RISK PARAMETER FILE\n" * 8)

    evidence = CmeSpanRiskProvider(str(source)).fetch(as_of=AS_OF)
    payload = evidence.to_dict()

    assert payload["provider_id"] == "cme-margin-data"
    assert payload["dataset_role"] == "margin_collateral"
    assert payload["byte_count"] == source.stat().st_size
    assert len(payload["content_sha256"]) == 64
    assert payload["individual_margin_requirement_inferred"] is False
    assert payload["decision_authority_granted"] is False
    assert payload["real_money_authorized"] is False


def test_occ_ofra_allows_official_https_and_rejects_foreign_host() -> None:
    provider = OccOfraRiskProvider(
        "https://www.theocc.com/risk-management/ofra/example-file.dat",
        http_get=lambda *args, **kwargs: _Response(),
    )
    evidence = provider.fetch(as_of=AS_OF)
    assert evidence.provider_id == "occ-margin-data"
    assert "theocc.com" in evidence.source_identifier

    foreign = OccOfraRiskProvider(
        "https://example.com/ofra.dat",
        http_get=lambda *args, **kwargs: _Response(),
    )
    with pytest.raises(FreeDerivativeRiskError, match="official provider host"):
        foreign.fetch(as_of=AS_OF)


def _quotes() -> tuple[OptionQuoteRecord, ...]:
    values = []
    for days in (30, 60):
        expiration = AS_OF + timedelta(days=days)
        for strike in (98.0, 99.0, 100.0, 101.0, 102.0):
            values.append(
                OptionQuoteRecord(
                    instrument_id=f"option:SPY:{days}:{strike}",
                    underlying_instrument_id="equity:SPY",
                    expiration_at=expiration,
                    strike=strike,
                    option_right=OptionRight.CALL,
                    exercise_style=ExerciseStyle.EUROPEAN,
                    bid=4.9,
                    ask=5.1,
                    underlying_price=100.0,
                    risk_free_rate=0.04,
                    dividend_yield=0.01,
                    observed_at=AS_OF - timedelta(minutes=1),
                    available_at=AS_OF,
                    source_identifier=f"option-evidence:{days}:{strike}",
                )
            )
    return tuple(values)


def test_internal_surface_compiler_does_not_self_certify() -> None:
    provider = DerivedVolatilitySurfaceProvider(
        {
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_BINDING": "canonical-option-quotes",
        }
    )

    surface = provider.build(_quotes(), as_of=AS_OF)

    assert surface.method_version == "black-scholes-bisection.v1"
    assert len(surface.points) == 10
    assert provider.configured is True
    assert provider.model_approved is False
    assert provider.certification_present is False
    assert provider.governance_ready is False
    assert provider.status()["self_certification_allowed"] is False


def test_surface_governance_requires_binding_approval_and_certification() -> None:
    provider = DerivedVolatilitySurfaceProvider(
        {
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_BINDING": "canonical-option-quotes",
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_MODEL_APPROVAL": "approved",
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_CERTIFICATION_ID": "cert:test:surface",
        }
    )
    assert provider.governance_ready is True


def test_preflight_preserves_three_margin_source_requirement(tmp_path) -> None:
    cme = tmp_path / "cme.span"
    occ = tmp_path / "occ.ofra"
    cme.write_bytes(b"CME SPAN RISK DATA\n" * 8)
    occ.write_bytes(b"OCC OFRA RISK DATA\n" * 8)
    report = preflight_free_derivative_risk_resources(
        as_of=AS_OF,
        environment={
            "CAPITAL_INTELLIGENCE_CME_MARGIN_BINDING": str(cme),
            "CAPITAL_INTELLIGENCE_OCC_MARGIN_BINDING": str(occ),
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_BINDING": "canonical-option-quotes",
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_MODEL_APPROVAL": "approved",
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_CERTIFICATION_ID": "cert:test:surface",
        },
    ).to_dict()

    assert report["cme_span"]["resource_valid"] is True
    assert report["occ_ofra"]["resource_valid"] is True
    assert report["derived_volatility_surfaces"]["governance_ready"] is True
    assert report["derivative_margin_role_minimum_sources"] == 3
    assert report["free_margin_sources_available"] == 2
    assert report["margin_role_complete_from_free_sources_alone"] is False
    assert report["provider_activation_granted"] is False


def test_configured_invalid_resource_fails_closed(tmp_path) -> None:
    missing = tmp_path / "missing.span"
    report = preflight_free_derivative_risk_resources(
        as_of=AS_OF,
        environment={"CAPITAL_INTELLIGENCE_CME_MARGIN_BINDING": str(missing)},
    )

    assert report.blockers
    assert "cme-margin-data" in report.blockers[0]
