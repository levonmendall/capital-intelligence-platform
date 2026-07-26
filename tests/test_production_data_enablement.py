import pytest

from institutional_market.data_enablement import (
    DataEnablementStatus,
    ProviderCapability,
    evaluate_production_data,
)


def _capability(engine: str, **overrides) -> ProviderCapability:
    values = {
        "engine": engine,
        "provider": "licensed-provider",
        "licensed": True,
        "point_in_time": True,
        "historical_universe": True,
        "corporate_actions": True,
        "adjustment_policy_version": "price-adjustment.v1",
        "provenance_complete": True,
        "service_level_defined": True,
    }
    values.update(overrides)
    return ProviderCapability(**values)


def test_all_required_sources_enable_authoritative_decisions():
    report = evaluate_production_data(
        _capability(engine)
        for engine in ("market_breadth", "valuation", "technical_momentum", "risk")
    )
    assert report.status is DataEnablementStatus.AUTHORITATIVE
    assert report.authoritative_decisions_allowed is True
    assert report.synthetic_fallback_allowed is False


def test_missing_engine_keeps_production_data_partial():
    report = evaluate_production_data(
        _capability(engine)
        for engine in ("market_breadth", "valuation", "technical_momentum")
    )
    assert report.status is DataEnablementStatus.PARTIAL
    assert report.missing_engines == ("risk",)
    assert report.authoritative_decisions_allowed is False


def test_deficient_provider_discloses_exact_gaps():
    report = evaluate_production_data(
        (
            _capability("market_breadth"),
            _capability("valuation"),
            _capability("technical_momentum"),
            _capability("risk", corporate_actions=False, provenance_complete=False),
        )
    )
    assert report.deficient_engines == ("risk",)
    risk = report.to_dict()["capabilities"][-1]
    assert "corporate actions" in risk["deficiencies"]
    assert "complete provenance" in risk["deficiencies"]


def test_duplicate_and_unknown_engines_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_production_data((_capability("risk"), _capability("risk")))
    with pytest.raises(ValueError, match="unknown"):
        evaluate_production_data((_capability("other"),))
