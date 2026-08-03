"""Public intelligence API with lazy compatibility exports.

Lazy loading keeps the public API stable while preventing package
initialization from creating cycles with collective governance in
``committee``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ActiveGovernanceVeto": (
        "intelligence.governance",
        "ActiveGovernanceVeto",
    ),
    "AnalyticalEngineResult": (
        "intelligence.analytical_engine",
        "AnalyticalEngineResult",
    ),
    "BASIS_POINTS": (
        "intelligence.synthesis_weights",
        "BASIS_POINTS",
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
    "DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY": (
        "intelligence.governance",
        "DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY",
    ),
    "DEFAULT_SYNTHESIS_WEIGHT_POLICY": (
        "intelligence.synthesis_weights",
        "DEFAULT_SYNTHESIS_WEIGHT_POLICY",
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
    "EngineNormalizationPolicy": (
        "intelligence.normalization",
        "EngineNormalizationPolicy",
    ),
    "EngineSynthesisWeight": (
        "intelligence.synthesis_weights",
        "EngineSynthesisWeight",
    ),
    "EXPECTED_ENGINE_ORDER": (
        "intelligence.normalization",
        "EXPECTED_ENGINE_ORDER",
    ),
    "GlobalLiquidityEngine": (
        "intelligence.global_liquidity",
        "GlobalLiquidityEngine",
    ),
    "GlobalLiquidityRun": (
        "intelligence.global_liquidity",
        "GlobalLiquidityRun",
    ),
    "GOVERNANCE_POLICY_VERSION": (
        "intelligence.governance",
        "GOVERNANCE_POLICY_VERSION",
    ),
    "GovernanceIssue": (
        "intelligence.governance",
        "GovernanceIssue",
    ),
    "GovernanceStatus": (
        "intelligence.governance",
        "GovernanceStatus",
    ),
    "InstitutionalRegimePipeline": (
        "intelligence.regime_pipeline",
        "InstitutionalRegimePipeline",
    ),
    "InstitutionalRegimeRun": (
        "intelligence.regime_pipeline",
        "InstitutionalRegimeRun",
    ),
    "IssueSeverity": (
        "intelligence.governance",
        "IssueSeverity",
    ),
    "MarketBreadthEngine": (
        "intelligence.market_breadth",
        "MarketBreadthEngine",
    ),
    "MarketBreadthRun": (
        "intelligence.market_breadth",
        "MarketBreadthRun",
    ),
    "MissingWeightPolicy": (
        "intelligence.synthesis_weights",
        "MissingWeightPolicy",
    ),
    "MultiEngineGovernancePolicy": (
        "intelligence.governance",
        "MultiEngineGovernancePolicy",
    ),
    "MultiEngineGovernanceResult": (
        "intelligence.governance",
        "MultiEngineGovernanceResult",
    ),
    "MultiEngineGovernor": (
        "intelligence.governance",
        "MultiEngineGovernor",
    ),
    "MultiEngineNormalizationBundle": (
        "intelligence.normalization",
        "MultiEngineNormalizationBundle",
    ),
    "MultiEngineNormalizer": (
        "intelligence.normalization",
        "MultiEngineNormalizer",
    ),
    "MultiEngineSynthesisResult": (
        "intelligence.synthesis_weights",
        "MultiEngineSynthesisResult",
    ),
    "MultiEngineSynthesizer": (
        "intelligence.synthesis_weights",
        "MultiEngineSynthesizer",
    ),
    "NORMALIZATION_POLICY_VERSION": (
        "intelligence.normalization",
        "NORMALIZATION_POLICY_VERSION",
    ),
    "NormalizedEngineAssessment": (
        "intelligence.normalization",
        "NormalizedEngineAssessment",
    ),
    "PositiveConclusionCeiling": (
        "intelligence.governance",
        "PositiveConclusionCeiling",
    ),
    "RegimeSeriesLoad": (
        "intelligence.regime_pipeline",
        "RegimeSeriesLoad",
    ),
    "RegimeSeriesRequest": (
        "intelligence.regime_pipeline",
        "RegimeSeriesRequest",
    ),
    "RiskEngine": (
        "intelligence.risk",
        "RiskEngine",
    ),
    "RiskRun": (
        "intelligence.risk",
        "RiskRun",
    ),
    "ScoreOrientation": (
        "intelligence.normalization",
        "ScoreOrientation",
    ),
    "SQLiteAnalyticalEngineStore": (
        "intelligence.engine_store",
        "SQLiteAnalyticalEngineStore",
    ),
    "SQLiteGovernanceStore": (
        "intelligence.governance_store",
        "SQLiteGovernanceStore",
    ),
    "SQLiteNormalizationStore": (
        "intelligence.normalization_store",
        "SQLiteNormalizationStore",
    ),
    "SQLiteSynthesisStore": (
        "intelligence.synthesis_store",
        "SQLiteSynthesisStore",
    ),
    "ScenarioProbability": (
        "intelligence.cio_guidance",
        "ScenarioProbability",
    ),
    "SeriesLoadState": (
        "intelligence.regime_pipeline",
        "SeriesLoadState",
    ),
    "SYNTHESIS_WEIGHT_POLICY_VERSION": (
        "intelligence.synthesis_weights",
        "SYNTHESIS_WEIGHT_POLICY_VERSION",
    ),
    "SynthesisStatus": (
        "intelligence.synthesis_weights",
        "SynthesisStatus",
    ),
    "SynthesisWeightPolicy": (
        "intelligence.synthesis_weights",
        "SynthesisWeightPolicy",
    ),
    "TechnicalMomentumEngine": (
        "intelligence.technical_momentum",
        "TechnicalMomentumEngine",
    ),
    "TechnicalMomentumRun": (
        "intelligence.technical_momentum",
        "TechnicalMomentumRun",
    ),
    "ValuationEngine": (
        "intelligence.valuation",
        "ValuationEngine",
    ),
    "ValuationRun": (
        "intelligence.valuation",
        "ValuationRun",
    ),
    "VetoType": (
        "intelligence.governance",
        "VetoType",
    ),
    "WeightedEngineContribution": (
        "intelligence.synthesis_weights",
        "WeightedEngineContribution",
    ),
    "build_configured_market_breadth_engine": (
        "intelligence.market_breadth",
        "build_configured_market_breadth_engine",
    ),
    "build_configured_risk_engine": (
        "intelligence.risk",
        "build_configured_risk_engine",
    ),
    "build_configured_technical_momentum_engine": (
        "intelligence.technical_momentum",
        "build_configured_technical_momentum_engine",
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
    "AssetPolicySensitivity": ("intelligence.forward", "AssetPolicySensitivity"),
    "CurrencyAssessment": ("intelligence.forward", "CurrencyAssessment"),
    "CurrencyExposure": ("intelligence.forward", "CurrencyExposure"),
    "CurrencyObservation": ("intelligence.forward", "CurrencyObservation"),
    "CurrencyRegime": ("intelligence.forward", "CurrencyRegime"),
    "CurrencyTransmissionEngine": ("intelligence.forward", "CurrencyTransmissionEngine"),
    "ForwardIntelligenceBundle": ("intelligence.forward", "ForwardIntelligenceBundle"),
    "ForwardScenario": ("intelligence.forward", "ForwardScenario"),
    "ForwardSignal": ("intelligence.forward", "ForwardSignal"),
    "MarketTrendEngine": ("intelligence.forward", "MarketTrendEngine"),
    "MarketTrendObservation": ("intelligence.forward", "MarketTrendObservation"),
    "MonetaryAssessment": ("intelligence.forward", "MonetaryAssessment"),
    "MonetaryPolicyObservation": ("intelligence.forward", "MonetaryPolicyObservation"),
    "MonetaryPolicyTransmissionEngine": ("intelligence.forward", "MonetaryPolicyTransmissionEngine"),
    "PolicyMotive": ("intelligence.forward", "PolicyMotive"),
    "PolicyRegime": ("intelligence.forward", "PolicyRegime"),
    "StrategicBusinessEngine": ("intelligence.forward", "StrategicBusinessEngine"),
    "StrategicBusinessObservation": ("intelligence.forward", "StrategicBusinessObservation"),
    "StructuralThemeEngine": ("intelligence.forward", "StructuralThemeEngine"),
    "StructuralThemeObservation": ("intelligence.forward", "StructuralThemeObservation"),
    "ThemeAssessment": ("intelligence.forward", "ThemeAssessment"),
    "ThemeLink": ("intelligence.forward", "ThemeLink"),
    "ThemeNodeObservation": ("intelligence.forward", "ThemeNodeObservation"),
    "ThemeStage": ("intelligence.forward", "ThemeStage"),
    "TrendAssessment": ("intelligence.forward", "TrendAssessment"),
    "TrendStage": ("intelligence.forward", "TrendStage"),
    "build_forward_intelligence_bundle": ("intelligence.forward", "build_forward_intelligence_bundle"),
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
