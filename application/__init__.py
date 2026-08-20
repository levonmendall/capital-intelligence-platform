"""Application orchestration for canonical Capital Intelligence experiences.

The package root is intentionally lazy. Production CIO workers import specific
``application.*`` modules while operating inside a bounded service container; eagerly
loading every daily-intelligence, evidence, context, and reporting dependency at package
initialization needlessly retained a second application graph before specialist analysis
began. Public imports from ``application`` remain compatible through module ``__getattr__``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Final


# The repository connectivity audit is deliberately static and follows AST import edges.
# Keep the canonical application graph visible to that governance control without executing
# the expensive imports at runtime. TYPE_CHECKING is always false in normal Python execution.
if TYPE_CHECKING:
    import application.daily_intelligence
    import application.eligible_universe
    import application.environment_evidence
    import application.forecast_support
    import application.multi_asset_evidence
    import application.production_cio
    import application.production_context
    import application.production_context_adapter
    import application.production_context_contract
    import application.production_context_executor
    import application.production_context_runtime


_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "CertifiedEligibleUniversePublication": ("application.eligible_universe", "CertifiedEligibleUniversePublication"),
    "EligibleUniverseCertificationState": ("application.eligible_universe", "EligibleUniverseCertificationState"),
    "EligibleUniverseError": ("application.eligible_universe", "EligibleUniverseError"),
    "SQLiteCertifiedEligibleUniverseStore": ("application.eligible_universe", "SQLiteCertifiedEligibleUniverseStore"),
    "CertifiedDecisionEnvironmentSnapshot": ("application.environment_evidence", "CertifiedDecisionEnvironmentSnapshot"),
    "EnvironmentEvidenceError": ("application.environment_evidence", "EnvironmentEvidenceError"),
    "EnvironmentEvidenceIntegrityError": ("application.environment_evidence", "EnvironmentEvidenceIntegrityError"),
    "SQLiteEnvironmentEvidenceStore": ("application.environment_evidence", "SQLiteEnvironmentEvidenceStore"),
    "SubsequentEnvironmentObservation": ("application.environment_evidence", "SubsequentEnvironmentObservation"),
    "AssetMetricDefinition": ("application.multi_asset_evidence", "AssetMetricDefinition"),
    "AssetSpecificEvidencePacket": ("application.multi_asset_evidence", "AssetSpecificEvidencePacket"),
    "MetricDirection": ("application.multi_asset_evidence", "MetricDirection"),
    "MultiAssetEvidenceError": ("application.multi_asset_evidence", "MultiAssetEvidenceError"),
    "MultiAssetEvidenceIntegrityError": ("application.multi_asset_evidence", "MultiAssetEvidenceIntegrityError"),
    "OriginatingFactObservation": ("application.multi_asset_evidence", "OriginatingFactObservation"),
    "SQLiteAssetSpecificEvidenceStore": ("application.multi_asset_evidence", "SQLiteAssetSpecificEvidenceStore"),
    "TypedAssetMetric": ("application.multi_asset_evidence", "TypedAssetMetric"),
    "metric_definition": ("application.multi_asset_evidence", "metric_definition"),
    "ProductionCanonicalCIOContextProvider": ("application.production_cio", "ProductionCanonicalCIOContextProvider"),
    "ProductionContextManifest": ("application.production_cio", "ProductionContextManifest"),
    "ProductionCanonicalCIOContext": ("application.production_context_contract", "ProductionCanonicalCIOContext"),
    "ProductionCanonicalCIOExecutor": ("application.production_context_executor", "ProductionCanonicalCIOExecutor"),
    "EvidenceCertificationState": ("application.production_context", "EvidenceCertificationState"),
    "GovernedEvidenceLineage": ("application.production_context", "GovernedEvidenceLineage"),
    "ProductionCandidateEvidence": ("application.production_context", "ProductionCandidateEvidence"),
    "ProductionContextError": ("application.production_context", "ProductionContextError"),
    "ProductionContextEvidenceSnapshot": ("application.production_context", "ProductionContextEvidenceSnapshot"),
    "ProductionHoldingEvidence": ("application.production_context", "ProductionHoldingEvidence"),
    "SQLiteProductionContextStore": ("application.production_context", "SQLiteProductionContextStore"),
    "RepositoryProductionCanonicalCIOContextProvider": ("application.production_context_runtime", "RepositoryProductionCanonicalCIOContextProvider"),
    "CanonicalProductionContextAdapter": ("application.production_context_adapter", "RepositoryProductionCanonicalCIOContextProvider"),
    "CandidateForecastScenarioImpact": ("application.forecast_support", "CandidateForecastScenarioImpact"),
    "CandidateForecastSupport": ("application.forecast_support", "CandidateForecastSupport"),
    "ForecastSupportError": ("application.forecast_support", "ForecastSupportError"),
    "ForecastSupportIntegrityError": ("application.forecast_support", "ForecastSupportIntegrityError"),
    "ForecastSupportingProductionContextProvider": ("application.forecast_support", "ForecastSupportingProductionContextProvider"),
    "SQLiteCandidateForecastSupportStore": ("application.forecast_support", "SQLiteCandidateForecastSupportStore"),
    "build_production_context_provider": ("application.forecast_support", "build_production_context_provider"),
    "DailyCapitalIntelligenceService": ("application.daily_intelligence", "DailyCapitalIntelligenceService"),
    "DailyCapitalIntelligenceSnapshot": ("application.daily_intelligence", "DailyCapitalIntelligenceSnapshot"),
    "DailyIntelligenceCycle": ("application.daily_intelligence", "DailyIntelligenceCycle"),
    "DailyIntelligenceStatus": ("application.daily_intelligence", "DailyIntelligenceStatus"),
    "DailySnapshotRecord": ("application.daily_intelligence", "DailySnapshotRecord"),
    "SQLiteDailySnapshotStore": ("application.daily_intelligence", "SQLiteDailySnapshotStore"),
    "build_daily_capital_intelligence_snapshot": ("application.daily_intelligence", "build_daily_capital_intelligence_snapshot"),
    "daily_snapshot_to_dict": ("application.daily_intelligence", "daily_snapshot_to_dict"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
