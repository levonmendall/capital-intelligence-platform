from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise RuntimeError(f"expected patch anchor missing in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise RuntimeError(f"patch anchor not unique in {path}: count={text.count(old)}")
    file.write_text(text.replace(old, new, 1))


replace_once(
    "intelligence/predictive_market.py",
    '''from intelligence.forward_decision import (\n    DecisionTiming,\n    DecisionTimingPosture,\n    EvidenceAvailability,\n    ForwardDecisionContext,\n    ForwardDecisionDimension,\n    ForwardDimensionAssessment,\n    ThesisMonitor,\n    applicable_dimensions,\n    build_forward_decision_context,\n)\n''',
    '''from intelligence.forward_decision import (\n    DecisionTiming,\n    DecisionTimingPosture,\n    EvidenceAvailability,\n    ForwardDecisionContext,\n    ForwardDecisionDimension,\n    ForwardDimensionAssessment,\n    ThesisMonitor,\n    applicable_dimensions,\n    build_forward_decision_context,\n)\nfrom intelligence.forward_research import (\n    ForwardResearchEvidence,\n    enrich_forward_decision_context,\n)\n''',
)
replace_once(
    "intelligence/predictive_market.py",
    '''def build_predictive_market_intelligence(\n    *,\n    candidate: object,\n    features: object,\n    flow_observation: CapitalFlowObservation,\n    market: MarketSpecialistContext,\n    existing_forward_intelligence: ForwardIntelligenceBundle | None,\n) -> PredictiveMarketIntelligence:\n''',
    '''def build_predictive_market_intelligence(\n    *,\n    candidate: object,\n    features: object,\n    flow_observation: CapitalFlowObservation,\n    market: MarketSpecialistContext,\n    existing_forward_intelligence: ForwardIntelligenceBundle | None,\n    research_evidence: ForwardResearchEvidence | None = None,\n) -> PredictiveMarketIntelligence:\n''',
)
replace_once(
    "intelligence/predictive_market.py",
    '''    decision_context = (\n        build_predictive_forward_decision_context(\n            candidate=candidate,\n            flow=flow,\n            expectations=expectations,\n            market=enriched_market,\n            existing_forward_intelligence=existing_forward_intelligence,\n        )\n        if isinstance(candidate, CandidateDecisionRecord)\n        else None\n    )\n    predictive_bundle = ForwardIntelligenceBundle(\n''',
    '''    decision_context = (\n        build_predictive_forward_decision_context(\n            candidate=candidate,\n            flow=flow,\n            expectations=expectations,\n            market=enriched_market,\n            existing_forward_intelligence=existing_forward_intelligence,\n        )\n        if isinstance(candidate, CandidateDecisionRecord)\n        else None\n    )\n    if decision_context is not None:\n        decision_context = enrich_forward_decision_context(\n            decision_context,\n            research_evidence,\n        )\n    predictive_bundle = ForwardIntelligenceBundle(\n''',
)
replace_once(
    "intelligence/predictive_market.py",
    '''        model_versions=(\n            CapitalFlowEngine.version,\n            MarketExpectationsEngine.version,\n            *((decision_context.schema_version,) if decision_context is not None else ()),\n        ),\n''',
    '''        model_versions=(\n            CapitalFlowEngine.version,\n            MarketExpectationsEngine.version,\n            *((research_evidence.schema_version,) if research_evidence is not None else ()),\n            *((decision_context.schema_version,) if decision_context is not None else ()),\n        ),\n''',
)
replace_once(
    "intelligence/predictive_market.py",
    '''    evidence_identifiers = tuple(\n        dict.fromkeys(\n            (\n                *flow.signal.evidence_identifiers,\n                *expectations.signal.evidence_identifiers,\n            )\n        )\n    )\n''',
    '''    evidence_identifiers = tuple(\n        dict.fromkeys(\n            (\n                *flow.signal.evidence_identifiers,\n                *expectations.signal.evidence_identifiers,\n                *(research_evidence.evidence_identifiers if research_evidence is not None else ()),\n            )\n        )\n    )\n''',
)
replace_once(
    "intelligence/predictive_market.py",
    '''        model_versions=(\n            ("capital_flow", CapitalFlowEngine.version),\n            ("market_expectations", MarketExpectationsEngine.version),\n        ),\n''',
    '''        model_versions=(\n            ("capital_flow", CapitalFlowEngine.version),\n            ("market_expectations", MarketExpectationsEngine.version),\n            *(((("forward_research", research_evidence.schema_version),)) if research_evidence is not None else ()),\n        ),\n''',
)
replace_once(
    "intelligence/__init__.py",
    '''    "build_forward_decision_context": ("intelligence.forward_decision", "build_forward_decision_context"),\n}\n''',
    '''    "build_forward_decision_context": ("intelligence.forward_decision", "build_forward_decision_context"),\n    "CertifiedExpectationObservation": ("intelligence.forward_research", "CertifiedExpectationObservation"),\n    "ExpectationEvidenceKind": ("intelligence.forward_research", "ExpectationEvidenceKind"),\n    "ExpectationsIntelligence": ("intelligence.forward_research", "ExpectationsIntelligence"),\n    "ExpectationsIntelligenceEngine": ("intelligence.forward_research", "ExpectationsIntelligenceEngine"),\n    "ForwardOpportunityDiscoveryEngine": ("intelligence.forward_research", "ForwardOpportunityDiscoveryEngine"),\n    "ForwardOpportunityHypothesis": ("intelligence.forward_research", "ForwardOpportunityHypothesis"),\n    "ForwardResearchEvidence": ("intelligence.forward_research", "ForwardResearchEvidence"),\n    "GovernedNowcastingEngine": ("intelligence.forward_research", "GovernedNowcastingEngine"),\n    "NowcastEstimate": ("intelligence.forward_research", "NowcastEstimate"),\n    "NowcastObservation": ("intelligence.forward_research", "NowcastObservation"),\n    "NowcastTarget": ("intelligence.forward_research", "NowcastTarget"),\n    "PositioningEvidenceKind": ("intelligence.forward_research", "PositioningEvidenceKind"),\n    "PositioningIntelligence": ("intelligence.forward_research", "PositioningIntelligence"),\n    "PositioningIntelligenceEngine": ("intelligence.forward_research", "PositioningIntelligenceEngine"),\n    "PositioningObservation": ("intelligence.forward_research", "PositioningObservation"),\n    "ResearchExposure": ("intelligence.forward_research", "ResearchExposure"),\n    "ValueOfWaitingAssessment": ("intelligence.forward_research", "ValueOfWaitingAssessment"),\n    "ValueOfWaitingEngine": ("intelligence.forward_research", "ValueOfWaitingEngine"),\n    "ValueOfWaitingInputs": ("intelligence.forward_research", "ValueOfWaitingInputs"),\n    "enrich_forward_decision_context": ("intelligence.forward_research", "enrich_forward_decision_context"),\n    "expectation_observations_from_snapshot": ("intelligence.forward_research", "expectation_observations_from_snapshot"),\n    "nowcast_observations_from_snapshot": ("intelligence.forward_research", "nowcast_observations_from_snapshot"),\n    "positioning_observations_from_snapshot": ("intelligence.forward_research", "positioning_observations_from_snapshot"),\n}\n''',
)
