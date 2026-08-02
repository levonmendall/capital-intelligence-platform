from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations.comprehensive_market_discovery import ComprehensiveMarketDiscoveryPolicy
from operations.market_discovery_preselection import CatalogScreeningSignal
from operations.provider_enriched_preselection import (
    REQUIRED_PROVIDER_FACTORS,
    provider_enriched_catalog_screening_signals,
    validate_provider_enriched_signals,
)


def _record(symbol: str = "ABC") -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        provider_symbol=f"{symbol}.US",
        name=f"{symbol} Incorporated",
        venue="US",
        country_code="US",
        currency="USD",
        instrument_type="common_stock",
        source_identifier=f"directory:{symbol}",
        economic_exposure="us_equity",
        quote_spread_bps=5.0,
        expiration_at=None,
    )


def _factor(
    name: str,
    *,
    observed_at: datetime,
    score: float,
    raw_value: float,
) -> dict[str, object]:
    return {
        "score": score,
        "raw_value": raw_value,
        "units": "normalized-provider-measure",
        "horizon_days": 90,
        "provider": "TEST_PROVIDER",
        "methodology_version": f"{name}.v1",
        "observed_at": observed_at.isoformat(),
        "evidence_identifiers": [f"provider-record:{name}:ABC"],
    }


def _publication(
    *,
    available_at: datetime,
    factors: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_factors = factors or {
        "value": _factor(
            "value", observed_at=available_at - timedelta(minutes=5), score=0.8, raw_value=0.07
        ),
        "momentum": _factor(
            "momentum", observed_at=available_at - timedelta(minutes=4), score=0.7, raw_value=0.12
        ),
        "carry": _factor(
            "carry", observed_at=available_at - timedelta(minutes=3), score=0.6, raw_value=0.03
        ),
        "improving_conditions": _factor(
            "improving_conditions",
            observed_at=available_at - timedelta(minutes=2),
            score=0.9,
            raw_value=0.18,
        ),
    }
    return {
        "schema_version": "capital-intelligence-provider-preselection.v1",
        "available_at": available_at.isoformat(),
        "source_identifiers": ["provider-publication:test:1"],
        "signals": {
            "ABC": {
                "observed_at": (available_at - timedelta(minutes=1)).isoformat(),
                "eligible": True,
                "liquidity_score": 0.95,
                "quality_score": 0.85,
                "indicative_price": 100.0,
                "source_identifiers": ["provider-signal:ABC"],
                "factors": resolved_factors,
            }
        },
    }


def test_default_provider_probe_populates_all_substantive_factors(tmp_path):
    as_of = datetime(2026, 8, 1, 15, tzinfo=timezone.utc)
    path = tmp_path / "provider-preselection.json"
    path.write_text(
        json.dumps(_publication(available_at=as_of - timedelta(minutes=1))),
        encoding="utf-8",
    )
    policy = ComprehensiveMarketDiscoveryPolicy(
        provider_preselection_path=str(path)
    )

    signal = provider_enriched_catalog_screening_signals(
        (_record(),), as_of, policy
    )["ABC"]

    assert signal.eligible is True
    assert signal.value_score == 0.8
    assert signal.momentum_score == 0.7
    assert signal.carry_score == 0.6
    assert signal.improving_conditions_score == 0.9
    for factor in REQUIRED_PROVIDER_FACTORS:
        assert any(
            identifier.startswith(f"provider-factor:{factor}:")
            for identifier in signal.evidence_identifiers
        )


def test_provider_probe_fails_closed_when_a_required_factor_is_missing(tmp_path):
    as_of = datetime(2026, 8, 1, 15, tzinfo=timezone.utc)
    factors = dict(
        _publication(available_at=as_of - timedelta(minutes=1))["signals"]["ABC"][
            "factors"
        ]
    )
    factors.pop("carry")
    path = tmp_path / "provider-preselection.json"
    path.write_text(
        json.dumps(
            _publication(
                available_at=as_of - timedelta(minutes=1), factors=factors
            )
        ),
        encoding="utf-8",
    )

    signal = provider_enriched_catalog_screening_signals(
        (_record(),),
        as_of,
        ComprehensiveMarketDiscoveryPolicy(provider_preselection_path=str(path)),
    )["ABC"]

    assert signal.eligible is False
    assert "provider_factor_carry_unavailable" in signal.exclusion_reasons


def test_unprovenanced_factor_scores_cannot_enter_provider_selection():
    as_of = datetime(2026, 8, 1, 15, tzinfo=timezone.utc)
    raw = CatalogScreeningSignal(
        symbol="ABC",
        observed_at=as_of,
        liquidity_score=0.9,
        quality_score=0.8,
        value_score=0.8,
        momentum_score=0.7,
        carry_score=0.6,
        improving_conditions_score=0.9,
        evidence_identifiers=("provider-record:generic",),
    )

    signal = validate_provider_enriched_signals(
        (_record(),), {"ABC": raw}
    )["ABC"]

    assert signal.eligible is False
    for factor in REQUIRED_PROVIDER_FACTORS:
        assert (
            f"provider_factor_{factor}_unprovenanced"
            in signal.exclusion_reasons
        )


def test_future_known_provider_publication_is_rejected(tmp_path):
    as_of = datetime(2026, 8, 1, 15, tzinfo=timezone.utc)
    path = tmp_path / "provider-preselection.json"
    path.write_text(
        json.dumps(_publication(available_at=as_of + timedelta(minutes=1))),
        encoding="utf-8",
    )

    signal = provider_enriched_catalog_screening_signals(
        (_record(),),
        as_of,
        ComprehensiveMarketDiscoveryPolicy(provider_preselection_path=str(path)),
    )["ABC"]

    assert signal.eligible is False
    assert any(
        reason.startswith("provider_enriched_preselection_publication_invalid")
        for reason in signal.exclusion_reasons
    )
