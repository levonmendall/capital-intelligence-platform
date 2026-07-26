"""Public intelligence API with lazy compatibility exports.

Lazy loading keeps the public API stable while preventing package
initialization from creating cycles with collective governance in
``committee``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "AnalyticalEngineResult": (
        "intelligence.analytical_engine",
        "AnalyticalEngineResult",
    ),
    "AnalyticalEngineCycleExecutor": (
        "intelligence.engine_cycle",
        "AnalyticalEngineCycleExecutor",
    ),
    "BusinessCycleEngine": (
        "intelligence.business_cycle",
        "BusinessCycleEngine",
    ),
    "BusinessCycleRun": (
        "intelligence.business_cycle",
        "BusinessCycleRun",
    ),
    "ChangeCondition": (
        "intelligence.cio_guidance",
        "ChangeCondition",
    ),
    "ChiefInvestmentOfficer": (
        "intelligence.cio",
        "ChiefInvestmentOfficer",
    ),
    "CIOBriefing": (
        "intelligence.briefing",
        "CIOBriefing",
    ),
    "CIOGuidance": (
        "intelligence.cio_guidance",
        "CIOGuidance",
    ),
    "CIOReflection": (
        "intelligence.reflection",
        "CIOReflection",
    ),
    "ConfidenceScores": (
        "intelligence.cio_guidance",
        "ConfidenceScores",
    ),
    "CreditCycleEngine": (
        "intelligence.credit_cycle",
        "CreditCycleEngine",
    ),
    "CreditCycleRun": (
        "intelligence.credit_cycle",
        "CreditCycleRun",
    ),
    "DocumentMetadata": (
        "intelligence.metadata",
        "DocumentMetadata",
    ),
    "DocumentStatus": (
        "intelligence.metadata",
        "DocumentStatus",
    ),
    "EngineDataStatus": (
        "intelligence.analytical_engine",
        "EngineDataStatus",
    ),
    "EngineDirection": (
        "intelligence.analytical_engine",
        "EngineDirection",
    ),
    "EngineEvidence": (
        "intelligence.analytical_engine",
        "EngineEvidence",
    ),
    "GlobalLiquidityEngine": (
        "intelligence.global_liquidity",
        "GlobalLiquidityEngine",
    ),
    "GlobalLiquidityRun": (
        "intelligence.global_liquidity",
        "GlobalLiquidityRun",
    ),
    "GuidanceSynthesizer": (
        "intelligence.cio",
        "GuidanceSynthesizer",
    ),
    "InstitutionalRegimePipeline": (
        "intelligence.regime_pipeline",
        "InstitutionalRegimePipeline",
    ),
    "InstitutionalRegimeRun": (
        "intelligence.regime_pipeline",
        "InstitutionalRegimeRun",
    ),
    "LiquidityAwareCycleExecutor": (
        "intelligence.liquidity_cycle",
        "LiquidityAwareCycleExecutor",
    ),
    "MarketBreadthEngine": (
        "intelligence.market_breadth",
        "MarketBreadthEngine",
    ),
    "MarketBreadthRun": (
        "intelligence.market_breadth",
        "MarketBreadthRun",
    ),
    "RegimeSeriesLoad": (
        "intelligence.regime_pipeline",
        "RegimeSeriesLoad",
    ),
    "RegimeSeriesRequest": (
        "intelligence.regime_pipeline",
        "RegimeSeriesRequest",
    ),
    "SQLiteAnalyticalEngineStore": (
        "intelligence.engine_store",
        "SQLiteAnalyticalEngineStore",
    ),
    "ScenarioProbability": (
        "intelligence.cio_guidance",
        "ScenarioProbability",
    ),
    "SeriesLoadState": (
        "intelligence.regime_pipeline",
        "SeriesLoadState",
    ),
    "ValuationEngine": (
        "intelligence.valuation",
        "ValuationEngine",
    ),
    "ValuationRun": (
        "intelligence.valuation",
        "ValuationRun",
    ),
    "build_configured_market_breadth_engine": (
        "intelligence.market_breadth",
        "build_configured_market_breadth_engine",
    ),
    "build_configured_valuation_engine": (
        "intelligence.valuation",
        "build_configured_valuation_engine",
    ),
    "build_fred_business_cycle_engine": (
        "intelligence.business_cycle",
        "build_fred_business_cycle_engine",
    ),
    "build_fred_credit_cycle_engine": (
        "intelligence.credit_cycle",
        "build_fred_credit_cycle_engine",
    ),
    "build_fred_global_liquidity_engine": (
        "intelligence.global_liquidity",
        "build_fred_global_liquidity_engine",
    ),
    "build_fred_regime_pipeline": (
        "intelligence.regime_pipeline",
        "build_fred_regime_pipeline",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load one public export on first access."""

    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from exc

    value = getattr(
        import_module(module_name),
        attribute_name,
    )
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return public lazy exports for interactive discovery."""

    return sorted(set(globals()) | set(__all__))
