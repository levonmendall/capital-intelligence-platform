from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 match, found {count}: {old[:140]!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "cio/service.py",
    "from cio.committee import EvidenceVetoCategory, IndependentSpecialistPacket\n",
    "from cio.committee import EvidenceVetoCategory, IndependentSpecialistPacket\n"
    "from cio.growth_ensemble import (\n"
    "    AdaptiveRobustGrowthEnsemble,\n"
    "    GrowthEnsembleAssessment,\n"
    "    GrowthStage,\n"
    ")\n",
)
replace_once(
    "cio/service.py",
    '    version: str = "cio-synthesis.v6"\n',
    '    version: str = "cio-synthesis.v7-growth"\n',
)
replace_once(
    "cio/service.py",
    '''        policy_matrix: DecisionPolicyMatrix | None = None,
    ) -> None:
''',
    '''        policy_matrix: DecisionPolicyMatrix | None = None,
        growth_ensemble: AdaptiveRobustGrowthEnsemble | None = None,
    ) -> None:
''',
)
replace_once(
    "cio/service.py",
    '''        self.policy_matrix = policy_matrix or DecisionPolicyMatrix()
''',
    '''        self.policy_matrix = policy_matrix or DecisionPolicyMatrix()
        self.growth_ensemble = growth_ensemble or AdaptiveRobustGrowthEnsemble()
''',
)
replace_once(
    "cio/service.py",
    '''        prior_context: PriorDecisionContext | None = None,
    ) -> CIODecision:
''',
    '''        prior_context: PriorDecisionContext | None = None,
        analysis_lane: str = "acquisition",
    ) -> CIODecision:
''',
)
replace_once(
    "cio/service.py",
    '''        assessment_cap = round(
            assessment_cap * historical_learning.position_size_multiplier,
            8,
        )
''',
    '''        # Historical calibration is applied once to the final feasible cap.
        assessment_cap = round(assessment_cap, 8)
''',
)
replace_once(
    "cio/service.py",
    '''        supported_weight = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=assessment_cap,
            policy_profile=profile,
        )
''',
    '''        progressive_lane = str(analysis_lane).lower() in {
            "participation",
            "exploration",
        }
        supported_weight = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=assessment_cap,
            policy_profile=profile,
            allow_soft_failures=progressive_lane,
        )
''',
)
replace_once(
    "cio/service.py",
    '''        robustness = self.robust_assessor.assess(
            robustness_candidate,
            alternative_return=effective_alternative,
            position_weight=assessment_weight,
            policy_profile=profile,
        )
        dissent = specialists.strongest_dissent()
''',
    '''        robustness = self.robust_assessor.assess(
            robustness_candidate,
            alternative_return=effective_alternative,
            position_weight=assessment_weight,
            policy_profile=profile,
        )
        ensemble = self.growth_ensemble.assess(
            candidate,
            specialists,
            robustness,
            profile,
            analysis_lane=analysis_lane,
        )
        dissent = specialists.strongest_dissent()
''',
)
replace_once(
    "cio/service.py",
    '''            reconciliation=reconciliation,
            effective_alternative=effective_alternative,
            profile=profile,
        )
        action, position_weight, reason, hysteresis_applied, persistence_cycles = (
''',
    '''            reconciliation=reconciliation,
            effective_alternative=effective_alternative,
            profile=profile,
            analysis_lane=analysis_lane,
            ensemble=ensemble,
        )
        action, position_weight, reason, hysteresis_applied, persistence_cycles = (
''',
)
replace_once(
    "cio/service.py",
    '''        if historical_learning.status.value != "not_applicable":
            reason = f"{reason} {historical_learning.summary}"
''',
    '''        reason = f"{reason} Growth ensemble: {ensemble.explanation}"
        if historical_learning.status.value != "not_applicable":
            reason = f"{reason} {historical_learning.summary}"
''',
)
replace_once(
    "cio/service.py",
    '''        effective_alternative: float,
        profile: DecisionPolicyProfile,
    ) -> tuple[CIOAction, float | None, str]:
''',
    '''        effective_alternative: float,
        profile: DecisionPolicyProfile,
        analysis_lane: str,
        ensemble: GrowthEnsembleAssessment,
    ) -> tuple[CIOAction, float | None, str]:
''',
)
replace_once(
    "cio/service.py",
    '''        if high_confidence_opposition:
            roles = ", ".join(item.role.value for item in high_confidence_opposition)
''',
    '''        progressive_lane = str(analysis_lane).lower() in {
            "participation",
            "exploration",
        }
        if high_confidence_opposition and (
            not progressive_lane or len(high_confidence_opposition) >= 2
        ):
            roles = ", ".join(item.role.value for item in high_confidence_opposition)
''',
)
replace_once(
    "cio/service.py",
    '''        if (
            robustness.effective_probability_of_success
            < profile.minimum_probability_of_success
        ):
''',
    '''        if (
            not progressive_lane
            and robustness.effective_probability_of_success
            < profile.minimum_probability_of_success
        ):
''',
)
replace_once(
    "cio/service.py",
    '''        if (
            robustness.evidence_adjusted_return
            < profile.minimum_net_expected_return
        ):
''',
    '''        if (
            not progressive_lane
            and robustness.evidence_adjusted_return
            < profile.minimum_net_expected_return
        ):
''',
)
replace_once(
    "cio/service.py",
    '''        if opportunity_edge < profile.minimum_opportunity_edge:
''',
    '''        if not progressive_lane and opportunity_edge < profile.minimum_opportunity_edge:
''',
)
replace_once(
    "cio/service.py",
    '''        feasible_cap = round(
            feasible_cap
            * specialists.historical_learning.position_size_multiplier,
            8,
        )
''',
    '''        feasible_cap = round(
            feasible_cap
            * specialists.historical_learning.effective_position_multiplier,
            8,
        )
''',
)
replace_once(
    "cio/service.py",
    '''        if feasible_cap <= 0.0:
            return (
                CIOAction.WATCH,
                None,
                "The portfolio analysis did not identify a positive feasible allocation.",
            )
        robust_cap = self.robust_assessor.maximum_supported_weight(
''',
    '''        if feasible_cap <= 0.0:
            return (
                CIOAction.WATCH,
                None,
                "The portfolio analysis did not identify a positive feasible allocation.",
            )
        if progressive_lane and ensemble.stage is GrowthStage.OBSERVE:
            return (
                CIOAction.WATCH,
                None,
                "Independent return engines do not yet support even an exploratory allocation.",
            )
        robust_cap = self.robust_assessor.maximum_supported_weight(
''',
)
replace_once(
    "cio/service.py",
    '''        robust_cap = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=feasible_cap,
            policy_profile=profile,
        )
''',
    '''        robust_cap = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=min(
                feasible_cap,
                ensemble.maximum_target_weight or feasible_cap,
            ),
            policy_profile=profile,
            allow_soft_failures=progressive_lane,
        )
''',
)
replace_once(
    "cio/service.py",
    '''        target = self._confidence_aware_target(
            robust_cap=robust_cap,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
        )
''',
    '''        target = self._confidence_aware_target(
            robust_cap=robust_cap,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
            ensemble=ensemble,
        )
''',
)
replace_once(
    "cio/service.py",
    '''        reconciliation: ReturnReconciliation,
        profile: DecisionPolicyProfile,
    ) -> float:
''',
    '''        reconciliation: ReturnReconciliation,
        profile: DecisionPolicyProfile,
        ensemble: GrowthEnsembleAssessment,
    ) -> float:
''',
)
replace_once(
    "cio/service.py",
    '''        scale = min(evidence_scale, probability_scale, edge_scale)
        return round(max(0.0, robust_cap * scale), 8)
''',
    '''        blended = (
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
''',
)

replace_once(
    "application/cio_cycle.py",
    '''                capital_comparison=ranked.qualification.capital_comparison,
                prior_context=prior_map.get(candidate.identifier),
            )
''',
    '''                capital_comparison=ranked.qualification.capital_comparison,
                prior_context=prior_map.get(candidate.identifier),
                analysis_lane=ranked.qualification.analysis_lane.value,
            )
''',
)
print("CIO growth ensemble integration patched")
