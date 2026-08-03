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
    replace_once(
        "cio/persistence.py",
        """    CONSTRUCTION_RECONCILIATION = \"construction_reconciliation\"
    DECISION_EVIDENCE_SNAPSHOT = \"decision_evidence_snapshot\"
""",
        """    CONSTRUCTION_RECONCILIATION = \"construction_reconciliation\"
    CANDIDATE_RISK_ASSESSMENT = \"candidate_risk_assessment\"
    JOINT_CANDIDATE_ASSESSMENT = \"joint_candidate_assessment\"
    DECISION_EVIDENCE_SNAPSHOT = \"decision_evidence_snapshot\"
""",
    )

    replace_once(
        "application/cio_cycle.py",
        """from portfolio.scenario_authority import (
""",
        """from portfolio.risk_intelligence import (
    CandidateRiskAssessment,
    CandidateRiskIntelligenceEngine,
    JointCandidateAssessment,
    JointCandidateIntelligenceEngine,
)
from portfolio.scenario_authority import (
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """    construction_reconciliations: tuple[
        ConstructionDecisionReconciliation, ...
    ]
    theses: tuple[LivingThesis, ...]
""",
        """    construction_reconciliations: tuple[
        ConstructionDecisionReconciliation, ...
    ]
    risk_assessments: tuple[CandidateRiskAssessment, ...]
    joint_candidate_assessments: tuple[JointCandidateAssessment, ...]
    theses: tuple[LivingThesis, ...]
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        if len(self.construction_reconciliations) != len(self.decisions):
            raise ValueError(
                \"each CIO decision must have one construction reconciliation\"
            )
        if not isinstance(self.theses, tuple) or not all(
""",
        """        if len(self.construction_reconciliations) != len(self.decisions):
            raise ValueError(
                \"each CIO decision must have one construction reconciliation\"
            )
        if not isinstance(self.risk_assessments, tuple) or not all(
            isinstance(item, CandidateRiskAssessment)
            for item in self.risk_assessments
        ):
            raise TypeError(
                \"risk_assessments must contain CandidateRiskAssessment values\"
            )
        if len(self.risk_assessments) != len(self.decisions):
            raise ValueError(
                \"each CIO decision must have one candidate risk assessment\"
            )
        if not isinstance(self.joint_candidate_assessments, tuple) or not all(
            isinstance(item, JointCandidateAssessment)
            for item in self.joint_candidate_assessments
        ):
            raise TypeError(
                \"joint_candidate_assessments must contain JointCandidateAssessment values\"
            )
        if not isinstance(self.theses, tuple) or not all(
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        historical_learning_resolver: HistoricalLearningResolver | None = None,
    ) -> None:
""",
        """        historical_learning_resolver: HistoricalLearningResolver | None = None,
        risk_intelligence_engine: CandidateRiskIntelligenceEngine | None = None,
        joint_candidate_engine: JointCandidateIntelligenceEngine | None = None,
    ) -> None:
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        self.cycle_disposition_authority = CIOCycleDispositionAuthority()

    def run(
""",
        """        self.cycle_disposition_authority = CIOCycleDispositionAuthority()
        self.risk_intelligence_engine = (
            risk_intelligence_engine or CandidateRiskIntelligenceEngine()
        )
        self.joint_candidate_engine = (
            joint_candidate_engine or JointCandidateIntelligenceEngine()
        )

    def run(
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        ranked_by_candidate = {
            item.candidate.identifier: item for item in queue.ranked
        }
        for ranked in queue.ranked:
""",
        """        ranked_by_candidate = {
            item.candidate.identifier: item for item in queue.ranked
        }
        risk_assessments = tuple(
            self.risk_intelligence_engine.assess(
                ranked.candidate,
                portfolio_value=portfolio.portfolio_value,
                proposed_weight=max(
                    portfolio.current_weight(ranked.candidate.instrument.symbol),
                    min(
                        ranked.candidate.maximum_position_weight,
                        portfolio.current_weight(ranked.candidate.instrument.symbol)
                        + max(
                            0.0,
                            portfolio.cash_weight
                            - self.construction_engine.policy.minimum_cash_weight,
                        ),
                    ),
                ),
                alternative_return=(
                    ranked.qualification.effective_opportunity_cost
                ),
                invalidation_clarity=(
                    0.50
                    if opportunity_context.ranking_input(
                        ranked.candidate.identifier
                    ) is None
                    else opportunity_context.ranking_input(
                        ranked.candidate.identifier
                    ).invalidation_clarity_score
                ),
            )
            for ranked in queue.ranked
        )
        risk_by_candidate = {
            item.candidate_identifier: item for item in risk_assessments
        }
        joint_candidate_assessments = self.joint_candidate_engine.assess(
            tuple(item.candidate for item in queue.ranked),
            risk_assessments,
            tuple(
                portfolio.profile(item.candidate.identifier)
                for item in queue.ranked
            ),
        )
        joint_by_candidate: dict[str, list[JointCandidateAssessment]] = {}
        for item in joint_candidate_assessments:
            joint_by_candidate.setdefault(
                item.first_candidate_identifier, []
            ).append(item)
            joint_by_candidate.setdefault(
                item.second_candidate_identifier, []
            ).append(item)
        if self.journal is not None:
            for item in risk_assessments:
                self.journal.append(
                    event_type=CIOJournalEventType.CANDIDATE_RISK_ASSESSMENT,
                    aggregate_identifier=item.candidate_identifier,
                    occurred_at=portfolio.as_of,
                    payload={
                        **item.to_dict(),
                        \"cycle_identifier\": cycle_identifier,
                        \"code_version\": code_version or \"unknown\",
                    },
                    schema_version=\"candidate-risk-assessment.v1\",
                    event_identifier=(
                        f\"event:candidate-risk:{cycle_identifier}:{item.candidate_identifier}\"
                    ),
                )
            for index, item in enumerate(joint_candidate_assessments, start=1):
                self.journal.append(
                    event_type=CIOJournalEventType.JOINT_CANDIDATE_ASSESSMENT,
                    aggregate_identifier=cycle_identifier,
                    occurred_at=portfolio.as_of,
                    payload={
                        **item.to_dict(),
                        \"cycle_identifier\": cycle_identifier,
                        \"code_version\": code_version or \"unknown\",
                    },
                    schema_version=\"joint-candidate-assessment.v1\",
                    event_identifier=(
                        f\"event:joint-candidate:{cycle_identifier}:{index}\"
                    ),
                )
        for ranked in queue.ranked:
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """            portfolio_context = self._preview_portfolio(
                candidate=candidate,
                rank=ranked.rank,
                portfolio=portfolio,
                effective_opportunity_cost=(
                    ranked.qualification.effective_opportunity_cost
                ),
            )
            if cycle_identifier.startswith(\"historical-canonical-cycle:\"):
""",
        """            portfolio_context = self._preview_portfolio(
                candidate=candidate,
                rank=ranked.rank,
                portfolio=portfolio,
                effective_opportunity_cost=(
                    ranked.qualification.effective_opportunity_cost
                ),
            )
            candidate_risk = risk_by_candidate[candidate.identifier]
            pair_evidence = tuple(
                (
                    f\"Joint candidate relation={item.relation.value}; \"
                    f\"tail dependence={item.tail_dependence:.0%}; \"
                    f\"{item.explanation}\"
                )
                for item in joint_by_candidate.get(candidate.identifier, ())
            )
            portfolio_context = replace(
                portfolio_context,
                constraint_evidence=tuple(
                    dict.fromkeys(
                        portfolio_context.constraint_evidence
                        + candidate_risk.diagnostics
                        + pair_evidence
                    )
                ),
                implementation_blocks=tuple(
                    dict.fromkeys(
                        portfolio_context.implementation_blocks
                        + candidate_risk.hard_blocks
                    )
                ),
                review_conditions=tuple(
                    dict.fromkeys(
                        portfolio_context.review_conditions
                        + (
                            \"Reassess candidate expected shortfall, conditional loss, recovery time, stress liquidity, thesis fragility, and joint portfolio relationships\",
                        )
                    )
                ),
            )
            if cycle_identifier.startswith(\"historical-canonical-cycle:\"):
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """            construction=construction,
            construction_reconciliations=construction_reconciliations,
            theses=theses,
""",
        """            construction=construction,
            construction_reconciliations=construction_reconciliations,
            risk_assessments=risk_assessments,
            joint_candidate_assessments=joint_candidate_assessments,
            theses=theses,
""",
    )

    replace_once(
        "tests/test_canonical_cio_cycle.py",
        """    assert journal.count() == 9
""",
        """    assert journal.count() == 10
""",
    )


if __name__ == "__main__":
    main()
