"""Explicit dispositions for modules that are intentionally outside live runtime reachability.

Static import reachability is not the same thing as architectural intent.  Some modules
are research/shadow analytics, offline certification tools, compatibility facades, or
superseded generations.  Every such module is named here so CI can distinguish an
intentional non-live capability from an accidentally orphaned production feature.

A disposition never grants investment or execution authority.  Promoting a SHADOW or
EXPERIMENTAL module into the live decision path requires a separate governed change,
production consumer, influence contract, counterfactual test, and release validation.
"""
from __future__ import annotations

from dataclasses import dataclass

from governance.runtime_influence_registry import ComponentLifecycle


@dataclass(frozen=True, slots=True)
class RuntimeModuleDisposition:
    module: str
    lifecycle: ComponentLifecycle
    rationale: str

    def __post_init__(self) -> None:
        if not self.module.strip():
            raise ValueError("module cannot be empty")
        if self.lifecycle is ComponentLifecycle.ORPHANED:
            raise ValueError("explicit dispositions cannot preserve an orphaned lifecycle")
        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")


RUNTIME_MODULE_DISPOSITIONS: tuple[RuntimeModuleDisposition, ...] = (
    RuntimeModuleDisposition(
        "application.mispriced_change_cycle",
        ComponentLifecycle.SUPERSEDED,
        "The production GlobalOpportunityRotationCanonicalCIOCycle already performs mispriced-change enrichment plus broader global rotation and joint portfolio preview.",
    ),
    RuntimeModuleDisposition(
        "cio.policy_governance",
        ComponentLifecycle.SHADOW,
        "Champion/challenger policy evaluation remains governance research and cannot self-promote into canonical CIO authority.",
    ),
    RuntimeModuleDisposition(
        "data.investment_graph_store",
        ComponentLifecycle.SHADOW,
        "Append-only persistence for the temporal investment-graph research capability; no live decision consumer is certified.",
    ),
    RuntimeModuleDisposition(
        "evaluation.causal_outcome_resolution",
        ComponentLifecycle.SHADOW,
        "Offline point-in-time resolution of causal predictions for evaluation; it has no live investment authority.",
    ),
    RuntimeModuleDisposition(
        "evaluation.cio_statistical_certification",
        ComponentLifecycle.SHADOW,
        "Measures resolved CIO process quality and explicitly cannot change thresholds, weights, construction policy, or capital authority.",
    ),
    RuntimeModuleDisposition(
        "evaluation.forecast_calibration",
        ComponentLifecycle.SHADOW,
        "Claim-level forecast calibration remains measurement-only until a separately governed feedback consumer is promoted.",
    ),
    RuntimeModuleDisposition(
        "evaluation.forecast_registry",
        ComponentLifecycle.SHADOW,
        "Append-only claim-level forecast research registry; records explicitly authorize neither policy nor portfolio changes.",
    ),
    RuntimeModuleDisposition(
        "evaluation.forecast_resolution",
        ComponentLifecycle.SHADOW,
        "Resolves claim-level research forecasts for calibration and evaluation rather than live CIO authority.",
    ),
    RuntimeModuleDisposition(
        "evaluation.global_rotation_certification",
        ComponentLifecycle.SHADOW,
        "Measures point-in-time global-rotation outcomes and explicitly cannot change policy or authorize capital.",
    ),
    RuntimeModuleDisposition(
        "evaluation.model_comparison",
        ComponentLifecycle.EXPERIMENTAL,
        "Offline champion-versus-challenger comparison used only for governed model experimentation and promotion review.",
    ),
    RuntimeModuleDisposition(
        "evaluation.strategy_replay",
        ComponentLifecycle.EXPERIMENTAL,
        "Offline strategy replay is an evaluation harness, not a production CIO or execution path.",
    ),
    RuntimeModuleDisposition(
        "governance.analytical_promotion",
        ComponentLifecycle.SHADOW,
        "Conservative promotion framework for validated shadow analytics; no live producer currently satisfies its certification boundary.",
    ),
    RuntimeModuleDisposition(
        "governance.champion_challenger",
        ComponentLifecycle.EXPERIMENTAL,
        "Explicit model-promotion authority is retained for governed experiments and is not an automatic live-policy mutation path.",
    ),
    RuntimeModuleDisposition(
        "governance.institutional_data_activation",
        ComponentLifecycle.SHADOW,
        "Institutional datasets remain disabled/shadow until licensing, point-in-time, provenance, freshness, certification, and fail-closed binding gates are satisfied.",
    ),
    RuntimeModuleDisposition(
        "governance.model_experiments",
        ComponentLifecycle.EXPERIMENTAL,
        "Defines shadow model experiments; challengers do not own live CIO decisions.",
    ),
    RuntimeModuleDisposition(
        "governance.runtime_influence_registry",
        ComponentLifecycle.OPERATIONAL,
        "CI architectural-control module invoked by the release connectivity audit rather than by the investment runtime itself.",
    ),
    RuntimeModuleDisposition(
        "intelligence",
        ComponentLifecycle.OPERATIONAL,
        "Package namespace only; decision authority belongs to explicitly imported intelligence implementations.",
    ),
    RuntimeModuleDisposition(
        "intelligence.asset_specific_underwriting",
        ComponentLifecycle.SHADOW,
        "Shadow-first underwriting explicitly produces zero decision impact unless complete drivers and separate decision certification exist.",
    ),
    RuntimeModuleDisposition(
        "intelligence.causal_investment_reasoning",
        ComponentLifecycle.SHADOW,
        "Claim-level causal explanation over existing event assessments; it creates no candidates, specialist votes, sizes, or portfolio actions.",
    ),
    RuntimeModuleDisposition(
        "intelligence.committee_members",
        ComponentLifecycle.OPERATIONAL,
        "Package namespace for committee-member implementations; no independent decision authority exists at the package initializer.",
    ),
    RuntimeModuleDisposition(
        "intelligence.document_change_analysis",
        ComponentLifecycle.SUPERSEDED,
        "Compatibility re-export of primary_source_documents rather than an independent production implementation.",
    ),
    RuntimeModuleDisposition(
        "intelligence.event_market",
        ComponentLifecycle.OPERATIONAL,
        "Stable public compatibility facade over the reachable event_market_forward implementation; it is not a second intelligence engine.",
    ),
    RuntimeModuleDisposition(
        "intelligence.forecast_calibration",
        ComponentLifecycle.SHADOW,
        "Calibration research is advisory and explicitly cannot raise confidence, sizing, expected return, thresholds, or execution authority.",
    ),
    RuntimeModuleDisposition(
        "intelligence.global_macro_overlay",
        ComponentLifecycle.SHADOW,
        "Hierarchical macro translation remains shadow until its observation families have certified point-in-time history.",
    ),
    RuntimeModuleDisposition(
        "intelligence.investment_graph",
        ComponentLifecycle.SHADOW,
        "Temporal investment-graph reasoning remains research-only until a governed live consumer and validation contract exist.",
    ),
    RuntimeModuleDisposition(
        "intelligence.primary_source_documents",
        ComponentLifecycle.SHADOW,
        "Primary-source document comparison is retained as research intelligence and has no certified live specialist consumer.",
    ),
    RuntimeModuleDisposition(
        "intelligence.structural_breaks",
        ComponentLifecycle.SHADOW,
        "Structural-break detection remains research evidence until separately validated and promoted through a governed consumer.",
    ),
    RuntimeModuleDisposition(
        "intelligence.thesis_learning",
        ComponentLifecycle.SHADOW,
        "Thesis-learning research is separate from the already-live conservative canonical historical-learning resolver.",
    ),
    RuntimeModuleDisposition(
        "intelligence.value_of_information",
        ComponentLifecycle.SHADOW,
        "Value-of-information research may prioritize evidence collection but has no certified decision or execution authority.",
    ),
    RuntimeModuleDisposition(
        "opportunity.relative_value",
        ComponentLifecycle.SHADOW,
        "Relative-value research is not a separately certified production opportunity authority; canonical/global-rotation ranking remains authoritative.",
    ),
    RuntimeModuleDisposition(
        "portfolio.atomic_relative_value_execution",
        ComponentLifecycle.EXPERIMENTAL,
        "Atomic relative-value execution is intentionally outside the canonical paper execution path and cannot be activated by reachability alone.",
    ),
    RuntimeModuleDisposition(
        "portfolio.digital_twin",
        ComponentLifecycle.SHADOW,
        "Portfolio digital-twin simulation is a research/evaluation capability and not construction or execution authority.",
    ),
    RuntimeModuleDisposition(
        "providers.databento_futures_history",
        ComponentLifecycle.OPERATIONAL,
        "Optional historical-provider adapter used by offline/backfill workflows; it is not required by the deployed runtime entrypoint graph.",
    ),
    RuntimeModuleDisposition(
        "providers.free_specialized_intelligence",
        ComponentLifecycle.SHADOW,
        "Credential-free USAspending/ClinicalTrials/NIH research explicitly supplies supporting evidence only and authorizes no candidate, ranking, sizing, portfolio change, or execution.",
    ),
    RuntimeModuleDisposition(
        "providers.market_data",
        ComponentLifecycle.SUPERSEDED,
        "Legacy latest-quote interface retained for compatibility while new multi-asset integrations use data.CanonicalMarketDataProvider.",
    ),
    RuntimeModuleDisposition(
        "providers.provider_activation_audit",
        ComponentLifecycle.OPERATIONAL,
        "Offline provider-activation audit utility; governance verification rather than live investment intelligence.",
    ),
)


MODULE_DISPOSITION_BY_NAME = {item.module: item for item in RUNTIME_MODULE_DISPOSITIONS}
if len(MODULE_DISPOSITION_BY_NAME) != len(RUNTIME_MODULE_DISPOSITIONS):
    raise RuntimeError("runtime module dispositions contain duplicate module names")


__all__ = [
    "MODULE_DISPOSITION_BY_NAME",
    "RUNTIME_MODULE_DISPOSITIONS",
    "RuntimeModuleDisposition",
]
