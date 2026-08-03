from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    # Preserve the existing lazy intelligence API and add the governed forward layer.
    replace_once(
        "intelligence/__init__.py",
        """    \"build_fred_regime_pipeline\": (
        \"intelligence.regime_pipeline\",
        \"build_fred_regime_pipeline\",
    ),
}
""",
        """    \"build_fred_regime_pipeline\": (
        \"intelligence.regime_pipeline\",
        \"build_fred_regime_pipeline\",
    ),
    \"AssetPolicySensitivity\": (\"intelligence.forward\", \"AssetPolicySensitivity\"),
    \"CurrencyAssessment\": (\"intelligence.forward\", \"CurrencyAssessment\"),
    \"CurrencyExposure\": (\"intelligence.forward\", \"CurrencyExposure\"),
    \"CurrencyObservation\": (\"intelligence.forward\", \"CurrencyObservation\"),
    \"CurrencyRegime\": (\"intelligence.forward\", \"CurrencyRegime\"),
    \"CurrencyTransmissionEngine\": (\"intelligence.forward\", \"CurrencyTransmissionEngine\"),
    \"ForwardIntelligenceBundle\": (\"intelligence.forward\", \"ForwardIntelligenceBundle\"),
    \"ForwardScenario\": (\"intelligence.forward\", \"ForwardScenario\"),
    \"ForwardSignal\": (\"intelligence.forward\", \"ForwardSignal\"),
    \"MarketTrendEngine\": (\"intelligence.forward\", \"MarketTrendEngine\"),
    \"MarketTrendObservation\": (\"intelligence.forward\", \"MarketTrendObservation\"),
    \"MonetaryAssessment\": (\"intelligence.forward\", \"MonetaryAssessment\"),
    \"MonetaryPolicyObservation\": (\"intelligence.forward\", \"MonetaryPolicyObservation\"),
    \"MonetaryPolicyTransmissionEngine\": (\"intelligence.forward\", \"MonetaryPolicyTransmissionEngine\"),
    \"PolicyMotive\": (\"intelligence.forward\", \"PolicyMotive\"),
    \"PolicyRegime\": (\"intelligence.forward\", \"PolicyRegime\"),
    \"StrategicBusinessEngine\": (\"intelligence.forward\", \"StrategicBusinessEngine\"),
    \"StrategicBusinessObservation\": (\"intelligence.forward\", \"StrategicBusinessObservation\"),
    \"StructuralThemeEngine\": (\"intelligence.forward\", \"StructuralThemeEngine\"),
    \"StructuralThemeObservation\": (\"intelligence.forward\", \"StructuralThemeObservation\"),
    \"ThemeAssessment\": (\"intelligence.forward\", \"ThemeAssessment\"),
    \"ThemeLink\": (\"intelligence.forward\", \"ThemeLink\"),
    \"ThemeNodeObservation\": (\"intelligence.forward\", \"ThemeNodeObservation\"),
    \"ThemeStage\": (\"intelligence.forward\", \"ThemeStage\"),
    \"TrendAssessment\": (\"intelligence.forward\", \"TrendAssessment\"),
    \"TrendStage\": (\"intelligence.forward\", \"TrendStage\"),
    \"build_forward_intelligence_bundle\": (\"intelligence.forward\", \"build_forward_intelligence_bundle\"),
}
""",
    )

    # Supply the bundle to the existing specialist service, not a new committee role.
    replace_once(
        "committee/specialists.py",
        """from company import CompanyAnalysis, CompanyFactor
""",
        """from company import CompanyAnalysis, CompanyFactor
from intelligence.forward import ForwardIntelligenceBundle
""",
    )
    replace_once(
        "committee/specialists.py",
        """    asset_valuation: AssetValuationSpecialistContext | None = None
    historical_learning: HistoricalLearningContext | None = None
""",
        """    asset_valuation: AssetValuationSpecialistContext | None = None
    forward_intelligence: ForwardIntelligenceBundle | None = None
    historical_learning: HistoricalLearningContext | None = None
""",
    )
    replace_once(
        "committee/specialists.py",
        """        if self.historical_learning is not None:
            if not isinstance(self.historical_learning, HistoricalLearningContext):
""",
        """        if self.forward_intelligence is not None:
            if not isinstance(self.forward_intelligence, ForwardIntelligenceBundle):
                raise TypeError(
                    \"forward_intelligence must be ForwardIntelligenceBundle or None\"
                )
            if self.forward_intelligence.candidate_identifier != self.candidate_identifier:
                raise ValueError(\"forward intelligence does not match candidate\")
            if self.forward_intelligence.as_of > self.analysis_completed_at:
                raise ValueError(\"forward intelligence cannot be from the future\")
        if self.historical_learning is not None:
            if not isinstance(self.historical_learning, HistoricalLearningContext):
""",
    )
    replace_once(
        "committee/specialists.py",
        """        analyses = (
            self._macro(candidate, context),
            self._market(candidate, context),
            self._forecast(candidate, context),
            self._fundamental(candidate, context),
            self._portfolio(candidate, context),
            self._evidence(candidate, context),
        )
        if context.historical_learning is not None:
""",
        """        analyses = (
            self._macro(candidate, context),
            self._market(candidate, context),
            self._forecast(candidate, context),
            self._fundamental(candidate, context),
            self._portfolio(candidate, context),
            self._evidence(candidate, context),
        )
        if context.forward_intelligence is not None:
            analyses = tuple(
                context.forward_intelligence.enrich_analysis(item)
                for item in analyses
            )
        if context.historical_learning is not None:
""",
    )

    # Carry forward intelligence through the canonical cycle boundary.
    replace_once(
        "application/cio_cycle.py",
        """from evaluation import DecisionEvidenceSnapshot
""",
        """from evaluation import DecisionEvidenceSnapshot
from intelligence.forward import ForwardIntelligenceBundle
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """    asset_valuation: AssetValuationSpecialistContext | None = None

    def __post_init__(self) -> None:
""",
        """    asset_valuation: AssetValuationSpecialistContext | None = None
    forward_intelligence: ForwardIntelligenceBundle | None = None

    def __post_init__(self) -> None:
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        if self.asset_valuation is not None and not isinstance(
            self.asset_valuation,
            AssetValuationSpecialistContext,
        ):
            raise TypeError(
                \"asset_valuation must be AssetValuationSpecialistContext or None\"
            )


@dataclass(frozen=True, slots=True)
class CanonicalCIOCycleResult:
""",
        """        if self.asset_valuation is not None and not isinstance(
            self.asset_valuation,
            AssetValuationSpecialistContext,
        ):
            raise TypeError(
                \"asset_valuation must be AssetValuationSpecialistContext or None\"
            )
        if self.forward_intelligence is not None:
            if not isinstance(self.forward_intelligence, ForwardIntelligenceBundle):
                raise TypeError(
                    \"forward_intelligence must be ForwardIntelligenceBundle or None\"
                )
            if self.forward_intelligence.candidate_identifier != self.candidate_identifier:
                raise ValueError(\"forward intelligence does not match candidate\")
            if self.forward_intelligence.as_of > self.analysis_completed_at:
                raise ValueError(\"forward intelligence cannot be from the future\")


@dataclass(frozen=True, slots=True)
class CanonicalCIOCycleResult:
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """                asset_valuation=base_context.asset_valuation,
                historical_learning=historical_learning,
""",
        """                asset_valuation=base_context.asset_valuation,
                forward_intelligence=base_context.forward_intelligence,
                historical_learning=historical_learning,
""",
    )

    # Persist and reconstruct the same point-in-time bundle in production.
    replace_once(
        "application/production_context.py",
        """from opportunity import (
""",
        """from intelligence.forward import ForwardIntelligenceBundle
from opportunity import (
""",
    )
    replace_once(
        "application/production_context.py",
        """    forecast: CrossAssetForecastSpecialistContext | None = None
    asset_valuation: AssetValuationSpecialistContext | None = None
""",
        """    forecast: CrossAssetForecastSpecialistContext | None = None
    asset_valuation: AssetValuationSpecialistContext | None = None
    forward_intelligence: ForwardIntelligenceBundle | None = None
""",
    )
    replace_once(
        "application/production_context.py",
        """        if self.asset_valuation is not None:
            if not isinstance(self.asset_valuation, AssetValuationSpecialistContext):
                raise TypeError(
                    \"asset_valuation must be AssetValuationSpecialistContext or None\"
                )
            if self.asset_valuation.as_of != self.as_of:
                raise ValueError(\"asset valuation evidence must share candidate as_of\")


@dataclass(frozen=True, slots=True)
class ProductionHoldingEvidence:
""",
        """        if self.asset_valuation is not None:
            if not isinstance(self.asset_valuation, AssetValuationSpecialistContext):
                raise TypeError(
                    \"asset_valuation must be AssetValuationSpecialistContext or None\"
                )
            if self.asset_valuation.as_of != self.as_of:
                raise ValueError(\"asset valuation evidence must share candidate as_of\")
        if self.forward_intelligence is not None:
            if not isinstance(self.forward_intelligence, ForwardIntelligenceBundle):
                raise TypeError(
                    \"forward_intelligence must be ForwardIntelligenceBundle or None\"
                )
            if self.forward_intelligence.candidate_identifier != self.candidate_identifier:
                raise ValueError(\"forward intelligence does not match candidate\")
            if self.forward_intelligence.as_of != self.as_of:
                raise ValueError(\"forward intelligence must share candidate as_of\")
            missing = set(self.forward_intelligence.evidence_identifiers).difference(
                self.lineage.evidence_identifiers
            )
            if missing:
                raise ValueError(
                    \"forward-intelligence evidence is absent from governed lineage: \"
                    + \", \".join(sorted(missing))
                )


@dataclass(frozen=True, slots=True)
class ProductionHoldingEvidence:
""",
    )
    replace_once(
        "application/production_context.py",
        """                asset_valuation=(
                    candidate_evidence[candidate_identifier].asset_valuation
                ),
            )
""",
        """                asset_valuation=(
                    candidate_evidence[candidate_identifier].asset_valuation
                ),
                forward_intelligence=(
                    candidate_evidence[candidate_identifier].forward_intelligence
                ),
            )
""",
    )
    replace_once(
        "application/production_context.py",
        """                | {
                    (
                        \"fundamental\",
                        item.fundamental_model_version,
                    )
                    for item in evidence.candidate_evidence
                }
            )
        )
""",
        """                | {
                    (
                        \"fundamental\",
                        item.fundamental_model_version,
                    )
                    for item in evidence.candidate_evidence
                }
                | {
                    (
                        f\"forward_intelligence:{item.candidate_identifier}\",
                        version,
                    )
                    for item in evidence.candidate_evidence
                    if item.forward_intelligence is not None
                    for version in item.forward_intelligence.model_versions
                }
            )
        )
""",
    )
    replace_once(
        "application/production_context.py",
        """        \"asset_valuation\": (
            None
            if value.asset_valuation is None
            else _asset_valuation_to_dict(value.asset_valuation)
        ),
        \"exposure_profile\": _profile_to_dict(value.exposure_profile),
""",
        """        \"asset_valuation\": (
            None
            if value.asset_valuation is None
            else _asset_valuation_to_dict(value.asset_valuation)
        ),
        \"forward_intelligence\": (
            None
            if value.forward_intelligence is None
            else value.forward_intelligence.to_dict()
        ),
        \"exposure_profile\": _profile_to_dict(value.exposure_profile),
""",
    )
    replace_once(
        "application/production_context.py",
        """    asset_valuation_payload = payload.get(\"asset_valuation\")
    return ProductionCandidateEvidence(
""",
        """    asset_valuation_payload = payload.get(\"asset_valuation\")
    forward_intelligence_payload = payload.get(\"forward_intelligence\")
    return ProductionCandidateEvidence(
""",
    )
    replace_once(
        "application/production_context.py",
        """        asset_valuation=(
            None
            if asset_valuation_payload is None
            else _asset_valuation_from_dict(dict(asset_valuation_payload))
        ),
    )
""",
        """        asset_valuation=(
            None
            if asset_valuation_payload is None
            else _asset_valuation_from_dict(dict(asset_valuation_payload))
        ),
        forward_intelligence=(
            None
            if forward_intelligence_payload is None
            else ForwardIntelligenceBundle.from_dict(
                dict(forward_intelligence_payload)
            )
        ),
    )
""",
    )


if __name__ == "__main__":
    main()
