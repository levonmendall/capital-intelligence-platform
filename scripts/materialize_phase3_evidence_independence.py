from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "cio/committee.py",
        """from cio.historical_learning import HistoricalLearningContext
from cio.models import (
""",
        """from cio.evidence_independence import (
    EvidenceIndependenceAssessment,
    assess_evidence_independence,
)
from cio.historical_learning import HistoricalLearningContext
from cio.models import (
""",
    )
    replace_once(
        "cio/committee.py",
        """    @property
    def median_confidence(self) -> float:
""",
        """    @property
    def evidence_independence(self) -> EvidenceIndependenceAssessment:
        return assess_evidence_independence(self.directional_analyses)

    @property
    def effective_directional_count(self) -> float:
        return self.evidence_independence.effective_role_count

    @property
    def evidence_independence_ratio(self) -> float:
        return self.evidence_independence.independence_ratio

    @property
    def independent_directional_support_ratio(self) -> float:
        return self.evidence_independence.independent_support_ratio

    @property
    def independent_confidence(self) -> float:
        return self.evidence_independence.independent_confidence

    def independent_opposition_count(self, minimum_confidence: float) -> int:
        return self.evidence_independence.independent_opposition_count(
            self.directional_analyses,
            minimum_confidence=float(minimum_confidence),
        )

    @property
    def median_confidence(self) -> float:
""",
    )

    replace_once(
        "cio/persistence.py",
        """        \"median_confidence\": packet.median_confidence,
        \"evidence_vetoes\": list(packet.evidence_vetoes),
""",
        """        \"median_confidence\": packet.median_confidence,
        \"independent_confidence\": packet.independent_confidence,
        \"effective_directional_count\": packet.effective_directional_count,
        \"evidence_independence_ratio\": packet.evidence_independence_ratio,
        \"independent_support_ratio\": packet.independent_directional_support_ratio,
        \"independent_cluster_count\": (
            packet.evidence_independence.independent_cluster_count
        ),
        \"evidence_vetoes\": list(packet.evidence_vetoes),
""",
    )

    replace_once(
        "cio/growth_ensemble.py",
        """        analyses = tuple(specialists.for_role(role) for role in self._RETURN_ROLES)
        active = tuple(
            item for item in analyses
            if item.position is not SpecialistPosition.ABSTAIN
        )
        coverage = len(active) / len(analyses)
        weight_total = sum(max(0.05, item.confidence) for item in active)
        alignment = (
            0.0
            if weight_total <= 0.0
            else sum(
                self._position_signal(item.position) * max(0.05, item.confidence)
                for item in active
            ) / weight_total
        )
        supportive = (
            0.0
            if not active
            else sum(
                item.position is SpecialistPosition.SUPPORTIVE for item in active
            ) / len(active)
        )
        confidence = self._geometric_mean(item.confidence for item in active)
""",
        """        analyses = tuple(specialists.for_role(role) for role in self._RETURN_ROLES)
        active = tuple(
            item for item in analyses
            if item.position is not SpecialistPosition.ABSTAIN
        )
        coverage = len(active) / len(analyses)
        independence = specialists.evidence_independence
        role_weight_total = sum(
            independence.weight_for(item.role) for item in active
        )
        weight_total = sum(
            max(0.05, item.confidence) * independence.weight_for(item.role)
            for item in active
        )
        alignment = (
            0.0
            if weight_total <= 0.0
            else sum(
                self._position_signal(item.position)
                * max(0.05, item.confidence)
                * independence.weight_for(item.role)
                for item in active
            ) / weight_total
        )
        supportive = (
            0.0
            if role_weight_total <= 0.0
            else sum(
                independence.weight_for(item.role)
                for item in active
                if item.position is SpecialistPosition.SUPPORTIVE
            ) / role_weight_total
        )
        confidence = independence.independent_confidence
""",
    )
    replace_once(
        "cio/growth_ensemble.py",
        """        raw_multiplier = (
            0.20 * reliability
            + 0.25 * agreement
            + 0.20 * supportive
            + 0.15 * confidence
            + 0.20 * edge_strength
        ) * uncertainty
""",
        """        raw_multiplier = (
            0.20 * reliability
            + 0.20 * agreement
            + 0.15 * supportive
            + 0.15 * confidence
            + 0.20 * edge_strength
            + 0.10 * independence.independence_ratio
        ) * uncertainty
""",
    )
    replace_once(
        "cio/growth_ensemble.py",
        """        if current >= 0.03 and alignment >= 0.20:
            stage = GrowthStage.ESTABLISHED
        elif lane == \"participation\" and coverage >= self.policy.minimum_engine_coverage:
            stage = GrowthStage.STRATEGIC
        elif alignment >= 0.45 and supportive >= 0.75 and robustness.robust_edge > 0.0:
            stage = GrowthStage.QUALIFIED
        elif alignment >= 0.10 and supportive >= 0.50:
            stage = GrowthStage.VALIDATE
        elif lane in {\"exploration\", \"participation\"} and alignment > -0.35:
            stage = GrowthStage.EXPLORE
        else:
            stage = GrowthStage.OBSERVE
""",
        """        effective = independence.effective_role_count
        if current >= 0.03 and alignment >= 0.20 and effective >= 2.0:
            stage = GrowthStage.ESTABLISHED
        elif (
            lane == \"participation\"
            and coverage >= self.policy.minimum_engine_coverage
            and effective >= 3.0
        ):
            stage = GrowthStage.STRATEGIC
        elif (
            alignment >= 0.45
            and supportive >= 0.75
            and robustness.robust_edge > 0.0
            and effective >= 3.0
        ):
            stage = GrowthStage.QUALIFIED
        elif alignment >= 0.10 and supportive >= 0.50 and effective >= 2.0:
            stage = GrowthStage.VALIDATE
        elif (
            lane in {\"exploration\", \"participation\"}
            and alignment > -0.35
            and effective >= 1.0
        ):
            stage = GrowthStage.EXPLORE
        else:
            stage = GrowthStage.OBSERVE
""",
    )
    replace_once(
        "cio/growth_ensemble.py",
        """            f\"{stage.value.title()} stage from {len(active)}/{len(analyses)} active \"
            f\"return engines; supportive={supportive:.0%}, alignment={alignment:+.2f}, \"
            f\"confidence={confidence:.0%}, robust edge={robustness.robust_edge:+.2%}. \"
""",
        """            f\"{stage.value.title()} stage from {len(active)}/{len(analyses)} active \"
            f\"return engines and {independence.effective_role_count:.2f} effective independent engines; \"
            f\"supportive={supportive:.0%}, alignment={alignment:+.2f}, \"
            f\"confidence={confidence:.0%}, independence={independence.independence_ratio:.0%}, \"
            f\"robust edge={robustness.robust_edge:+.2%}. \"
""",
    )

    replace_once(
        "cio/service.py",
        '    version: str = "cio-synthesis.v8-economic-consistency"\n',
        '    version: str = "cio-synthesis.v9-independent-evidence"\n',
    )
    replace_once(
        "cio/service.py",
        """                progressive_lane=progressive_lane,
                emergency=(
""",
        """                progressive_lane=progressive_lane,
                evidence_independence_ratio=(
                    specialists.evidence_independence_ratio
                ),
                emergency=(
""",
    )
    replace_once(
        "cio/service.py",
        """        reason = f\"{reason} Growth ensemble: {ensemble.explanation}\"
""",
        """        reason = (
            f\"{reason} Growth ensemble: {ensemble.explanation} \"
            f\"Committee evidence resolves to {specialists.effective_directional_count:.2f} \"
            f\"effective independent directional views from \"
            f\"{len(specialists.directional_active)} active roles.\"
        )
""",
    )
    replace_once(
        "cio/service.py",
        """        high_confidence_opposition = tuple(
            analysis
            for analysis in specialists.opposing
            if analysis.confidence
            >= self.policy.maximum_unresolved_dissent_confidence
        )
        progressive_lane = str(analysis_lane).lower() in {
            \"participation\",
            \"exploration\",
        }
        if high_confidence_opposition and (
            not progressive_lane or len(high_confidence_opposition) >= 2
        ):
""",
        """        high_confidence_opposition = tuple(
            analysis
            for analysis in specialists.opposing
            if analysis.confidence
            >= self.policy.maximum_unresolved_dissent_confidence
        )
        independent_opposition = specialists.independent_opposition_count(
            self.policy.maximum_unresolved_dissent_confidence
        )
        progressive_lane = str(analysis_lane).lower() in {
            \"participation\",
            \"exploration\",
        }
        if high_confidence_opposition and (
            (not progressive_lane and independent_opposition >= 1)
            or independent_opposition >= 2
        ):
""",
    )
    replace_once(
        "cio/service.py",
        """        progressive_lane: bool,
        emergency: bool,
""",
        """        progressive_lane: bool,
        evidence_independence_ratio: float,
        emergency: bool,
""",
    )
    replace_once(
        "cio/service.py",
        """        elif action in {CIOAction.REDUCE, CIOAction.EXIT}:
            required = max(1, profile.reduce_persistence_cycles)
            if prior_context is not None:
                observed = prior_context.consecutive_opposing_cycles + 1

        cooldown_active = False
""",
        """        elif action in {CIOAction.REDUCE, CIOAction.EXIT}:
            required = max(1, profile.reduce_persistence_cycles)
            if prior_context is not None:
                observed = prior_context.consecutive_opposing_cycles + 1

        if (
            action in {CIOAction.BUY, CIOAction.INCREASE}
            and evidence_independence_ratio < 0.75
        ):
            required += 1

        cooldown_active = False
""",
    )
    replace_once(
        "cio/service.py",
        """    def _confidence_aware_target(
        self,
        *,
        robust_cap: float,
        robustness: RobustCandidateAssessment,
        reconciliation: ReturnReconciliation,
        profile: DecisionPolicyProfile,
        ensemble: GrowthEnsembleAssessment,
        progressive_lane: bool,
    ) -> float:
        evidence_scale = min(1.0, robustness.evidence_reliability / 0.85)
        probability_scale = min(
            1.0,
            reconciliation.probability_of_success
            / max(profile.minimum_probability_of_success + 0.05, 0.60),
        )
        edge_scale = min(
            1.0,
            max(0.0, robustness.robust_edge)
            / max(profile.minimum_opportunity_edge * 2.0, 0.02),
        )
        if not progressive_lane:
            scale = min(evidence_scale, probability_scale, edge_scale)
            return round(max(0.0, robust_cap * scale), 8)
        blended = (
            evidence_scale * 0.35
            + probability_scale * 0.25
            + edge_scale * 0.20
            + ensemble.target_multiplier * 0.20
        )
        target = robust_cap * max(0.15, min(1.0, blended))
        if ensemble.stage is not GrowthStage.OBSERVE:
            target = max(
                target,
                min(robust_cap, ensemble.minimum_target_weight),
            )
        if ensemble.maximum_target_weight > 0.0:
            target = min(target, ensemble.maximum_target_weight)
        return round(max(0.0, target), 8)
""",
        """    def _confidence_aware_target(
        self,
        *,
        robust_cap: float,
        robustness: RobustCandidateAssessment,
        reconciliation: ReturnReconciliation,
        profile: DecisionPolicyProfile,
        ensemble: GrowthEnsembleAssessment,
        progressive_lane: bool,
    ) -> float:
        # RobustCandidateAssessor already incorporates evidence shrinkage,
        # probability consistency, downside, edge and stress.  Do not charge the
        # same uncertainty again through three independent minimum scales.
        target = robust_cap * max(0.20, min(1.0, ensemble.target_multiplier))
        if progressive_lane and ensemble.stage is not GrowthStage.OBSERVE:
            target = max(
                target,
                min(robust_cap, ensemble.minimum_target_weight),
            )
        if progressive_lane and ensemble.maximum_target_weight > 0.0:
            target = min(target, ensemble.maximum_target_weight)
        return round(max(0.0, target), 8)
""",
    )
    replace_once(
        "cio/service.py",
        """        directional = specialists.directional_support_ratio
        calculated = (
            candidate.evidence_quality.score * 0.35
            + specialists.evidence_confidence * 0.15
            + specialists.implementation_confidence * 0.10
            + specialists.median_confidence * 0.15
            + directional * 0.15
            + specialists.coverage_ratio * 0.10
        )
        origin_factor = min(1.0, reconciliation.evidence_origin_count / 4.0)
        calculated *= 0.70 + 0.20 * origin_factor + 0.10 * specialists.coverage_ratio
""",
        """        directional = specialists.independent_directional_support_ratio
        independence = specialists.evidence_independence
        calculated = (
            candidate.evidence_quality.score * 0.35
            + specialists.evidence_confidence * 0.15
            + specialists.implementation_confidence * 0.10
            + specialists.independent_confidence * 0.15
            + directional * 0.15
            + specialists.coverage_ratio * 0.10
        )
        origin_factor = min(1.0, reconciliation.evidence_origin_count / 4.0)
        calculated *= (
            0.55
            + 0.20 * origin_factor
            + 0.15 * independence.independence_ratio
            + 0.10 * specialists.coverage_ratio
        )
""",
    )


if __name__ == "__main__":
    main()
