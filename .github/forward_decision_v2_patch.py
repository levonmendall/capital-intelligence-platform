from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "intelligence/forward_decision.py",
    '        if self.availability is EvidenceAvailability.AVAILABLE and not self.evidence_identifiers:\n            raise ValueError("available forward dimensions require governed evidence identifiers")\n',
    '        if self.availability in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.PARTIAL} and not self.evidence_identifiers:\n            raise ValueError("available/partial forward dimensions require governed evidence identifiers")\n',
)

replace_once(
    "intelligence/predictive_market.py",
    "from intelligence.forward import (\n    ForwardIntelligenceBundle,\n    ForwardScenario,\n    ForwardSignal,\n)\n",
    "from intelligence.forward import (\n    ForwardIntelligenceBundle,\n    ForwardScenario,\n    ForwardSignal,\n)\nfrom intelligence.forward_decision import (\n    DecisionTiming,\n    DecisionTimingPosture,\n    EvidenceAvailability,\n    ForwardDecisionContext,\n    ForwardDecisionDimension,\n    ForwardDimensionAssessment,\n    ThesisMonitor,\n    build_forward_decision_context,\n)\n",
)

marker = "\n\n@dataclass(frozen=True, slots=True)\nclass PredictiveMarketIntelligence:"
helper = '''


def build_predictive_forward_decision_context(
    *,
    candidate: object,
    flow: CapitalFlowAssessment,
    expectations: MarketExpectationsAssessment,
    market: MarketSpecialistContext,
    existing_forward_intelligence: ForwardIntelligenceBundle | None,
) -> ForwardDecisionContext:
    """Map certified current evidence into a truthful common v2 packet."""
    candidate_identifier = _text(getattr(candidate, "identifier"), field_name="candidate identifier")
    as_of = _aware(getattr(candidate, "as_of"), field_name="candidate as_of")
    asset_class = getattr(getattr(candidate, "instrument"), "asset_class")
    candidate_ids = tuple(getattr(candidate, "evidence_identifiers", ()) or ())
    if not candidate_ids:
        raise ValueError("forward decision context requires candidate evidence identifiers")
    evidence_quality = float(getattr(getattr(candidate, "evidence_quality"), "score"))
    existing_signals = () if existing_forward_intelligence is None else existing_forward_intelligence.signals

    def from_signals(dimension, *, summary, channels=(), name_terms=()):
        selected = tuple(
            signal for signal in existing_signals
            if (channels and any(channel in signal.channels for channel in channels))
            or (name_terms and any(term in f"{signal.name} {signal.identifier}".lower() for term in name_terms))
        )
        identifiers = tuple(dict.fromkeys(identifier for signal in selected for identifier in signal.evidence_identifiers))
        if not selected or not identifiers:
            return None
        return ForwardDimensionAssessment(
            dimension=dimension,
            availability=EvidenceAvailability.PARTIAL,
            summary=summary,
            confidence=min(signal.confidence for signal in selected),
            evidence=tuple(dict.fromkeys(item for signal in selected for item in signal.evidence)),
            contradictory_evidence=tuple(dict.fromkeys(item for signal in selected for item in signal.contradictory_evidence)),
            assumptions=tuple(dict.fromkeys(item for signal in selected for item in signal.assumptions)),
            risks=tuple(dict.fromkeys(item for signal in selected for item in signal.risks)),
            change_conditions=tuple(dict.fromkeys(item for signal in selected for item in signal.change_conditions)),
            evidence_identifiers=identifiers,
        )

    assessments = [item for item in (
        from_signals(ForwardDecisionDimension.REGIME, summary="Governed Phase-5 macro and currency signals provide partial regime context", channels=("macro", "currency")),
        from_signals(ForwardDecisionDimension.FUNDAMENTALS, summary="Governed Phase-5 signals provide partial business and valuation trajectory context", channels=("fundamental",)),
        from_signals(ForwardDecisionDimension.CROSS_ASSET, summary="Governed macro, currency and forecast signals provide partial cross-asset confirmation", channels=("macro", "currency", "forecast")),
        from_signals(ForwardDecisionDimension.STRUCTURAL, summary="Governed structural-theme evidence provides partial value-chain transmission context", name_terms=("structural", "theme", "value-chain", "bottleneck")),
    ) if item is not None]

    assessments.append(ForwardDimensionAssessment(
        dimension=ForwardDecisionDimension.EXPECTATIONS,
        availability=EvidenceAvailability.AVAILABLE,
        summary=f"Evidence-backed outlook versus market-implied proxy gives expected surprise {expectations.expected_surprise:+.2%}; estimated priced-in score {expectations.priced_in_score:.0%}",
        confidence=expectations.confidence,
        evidence=expectations.diagnostics,
        contradictory_evidence=expectations.signal.contradictory_evidence,
        assumptions=expectations.signal.assumptions,
        risks=expectations.signal.risks,
        change_conditions=expectations.signal.change_conditions,
        evidence_identifiers=expectations.signal.evidence_identifiers,
        market_expectation=f"Market-implied proxy; estimated priced-in score {expectations.priced_in_score:.0%}",
        internal_expectation=f"Evidence-backed expected surprise {expectations.expected_surprise:+.2%}",
    ))

    catalysts = tuple(getattr(candidate, "primary_catalysts", ()) or ())
    if catalysts:
        assessments.append(ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.CATALYSTS,
            availability=EvidenceAvailability.PARTIAL,
            summary="Candidate catalysts are governed but no certified dated event calendar is attached; event timing and collision risk remain unresolved",
            confidence=min(0.75, evidence_quality),
            evidence=tuple(f"Candidate catalyst: {item}" for item in catalysts),
            assumptions=("Catalyst descriptions remain relevant through the next governed review",),
            risks=("Undated catalysts cannot support pre-event versus post-event timing decisions",),
            change_conditions=("Reassess when a certified event date or revised catalyst becomes available",),
            evidence_identifiers=candidate_ids,
        ))

    assessments.extend((
        ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.POSITIONING,
            availability=EvidenceAvailability.PARTIAL,
            summary=f"Price-and-volume market-behavior proxy indicates {flow.state.value}; complete institutional, fund, futures, dealer and cross-border positioning is not claimed",
            confidence=flow.confidence,
            evidence=flow.diagnostics,
            contradictory_evidence=flow.signal.contradictory_evidence,
            assumptions=flow.signal.assumptions,
            risks=flow.signal.risks,
            change_conditions=flow.signal.change_conditions,
            evidence_identifiers=flow.signal.evidence_identifiers,
        ),
        ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.MICROSTRUCTURE,
            availability=EvidenceAvailability.PARTIAL,
            summary="Liquidity and price/volume confirmation provide a partial market-structure view; order-book and dealer inventory evidence are not asserted",
            confidence=min(flow.confidence, float(market.confidence)),
            evidence=tuple(dict.fromkeys((*market.evidence, *flow.diagnostics))),
            contradictory_evidence=("No complete order-book, dealer inventory, or venue-fragmentation model is claimed",),
            assumptions=flow.signal.assumptions,
            risks=tuple(dict.fromkeys((*market.risks, *flow.signal.risks))),
            change_conditions=flow.signal.change_conditions,
            evidence_identifiers=tuple(dict.fromkeys((*market.evidence_identifiers, *flow.signal.evidence_identifiers))),
        ),
        ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.REFLEXIVITY,
            availability=EvidenceAvailability.PARTIAL,
            summary=f"Crowding/reversal proxies imply {flow.reversal_risk:.0%} reversal risk; forced-flow mechanics remain incomplete without certified dealer/leverage data",
            confidence=flow.confidence,
            evidence=flow.diagnostics,
            contradictory_evidence=("Short-covering and crowding are inferred from market behavior rather than complete owner/dealer books",),
            assumptions=flow.signal.assumptions,
            risks=flow.signal.risks,
            change_conditions=flow.signal.change_conditions,
            evidence_identifiers=flow.signal.evidence_identifiers,
        ),
    ))

    scenario_evidence = tuple(
        f"{point.label}: probability={point.probability:.1%}, return={point.total_return:+.2%}"
        for point in getattr(candidate, "scenario_distribution")
    )
    assessments.append(ForwardDimensionAssessment(
        dimension=ForwardDecisionDimension.PATH_RISK,
        availability=EvidenceAvailability.AVAILABLE,
        summary=f"Canonical candidate distribution spans bear/base/bull outcomes with expected downside {float(getattr(candidate, 'expected_downside')):+.2%} over {int(getattr(candidate, 'decision_horizon_days'))} days",
        confidence=evidence_quality,
        evidence=scenario_evidence,
        contradictory_evidence=tuple(getattr(candidate, "contradictory_evidence", ()) or ()),
        assumptions=tuple(getattr(candidate, "critical_assumptions", ()) or ()),
        risks=tuple(getattr(candidate, "key_risks", ()) or ()),
        change_conditions=tuple(getattr(candidate, "invalidation_conditions", ()) or ()),
        evidence_identifiers=candidate_ids,
    ))
    assessments.append(ForwardDimensionAssessment(
        dimension=ForwardDecisionDimension.PORTFOLIO_CONTEXT,
        availability=EvidenceAvailability.PARTIAL,
        summary=f"Pre-committee edge versus governed opportunity-cost baseline is {float(getattr(candidate, 'opportunity_edge')):+.2%}; current weight {float(getattr(candidate, 'current_portfolio_weight')):.2%}. Final best-alternative comparison remains downstream.",
        confidence=evidence_quality,
        evidence=(f"Net expected return={float(getattr(candidate, 'net_expected_return')):+.2%}", f"Opportunity-cost return={float(getattr(candidate, 'opportunity_cost_return')):+.2%}"),
        assumptions=("Final portfolio competition and constraints remain authoritative downstream",),
        risks=("An attractive standalone candidate can still be inferior to another use of portfolio capital",),
        change_conditions=("Reassess after changes in opportunity cost, holdings, cash hurdle, or competing candidates",),
        evidence_identifiers=candidate_ids,
    ))

    timing = DecisionTiming(
        posture=DecisionTimingPosture.NO_TIMING_EDGE,
        rationale="No certified dated catalyst calendar is attached, so v2 does not invent a pre-event/post-event timing edge",
        next_reassessment_at=_aware(getattr(candidate, "review_at"), field_name="candidate review_at"),
    )
    thesis_monitor = ThesisMonitor(
        thesis="Governed candidate thesis: " + "; ".join(catalysts[:2]),
        must_remain_true=tuple(getattr(candidate, "critical_assumptions", ()) or ()),
        invalidation_conditions=tuple(getattr(candidate, "invalidation_conditions", ()) or ()),
        monitor_evidence=tuple(getattr(candidate, "monitoring_indicators", ()) or ()),
    )
    return build_forward_decision_context(
        identifier=f"forward-decision:{candidate_identifier}:{as_of.isoformat()}",
        candidate_identifier=candidate_identifier,
        as_of=as_of,
        asset_class=asset_class,
        assessments=tuple(assessments),
        timing=timing,
        thesis_monitor=thesis_monitor,
    )
'''
path = Path("intelligence/predictive_market.py")
text = path.read_text()
if text.count(marker) != 1:
    raise SystemExit("predictive market insertion marker mismatch")
path.write_text(text.replace(marker, helper + marker, 1))

replace_once(
    "intelligence/predictive_market.py",
    '        currency_regime=existing.currency_regime or predictive.currency_regime,\n        schema_version="forward-intelligence.v2-predictive-market",\n',
    '        currency_regime=existing.currency_regime or predictive.currency_regime,\n        decision_context=predictive.decision_context or existing.decision_context,\n        schema_version="forward-intelligence.v2-predictive-market",\n',
)
replace_once(
    "intelligence/predictive_market.py",
    "    predictive_bundle = ForwardIntelligenceBundle(\n",
    "    decision_context = build_predictive_forward_decision_context(\n        candidate=candidate,\n        flow=flow,\n        expectations=expectations,\n        market=enriched_market,\n        existing_forward_intelligence=existing_forward_intelligence,\n    )\n    predictive_bundle = ForwardIntelligenceBundle(\n",
)
replace_once(
    "intelligence/predictive_market.py",
    '        model_versions=(CapitalFlowEngine.version, MarketExpectationsEngine.version),\n        schema_version="forward-intelligence.v2-predictive-market",\n',
    '        model_versions=(CapitalFlowEngine.version, MarketExpectationsEngine.version, decision_context.schema_version),\n        decision_context=decision_context,\n        schema_version="forward-intelligence.v2-predictive-market",\n',
)
replace_once(
    "intelligence/predictive_market.py",
    '    "build_predictive_market_intelligence",\n    "merge_forward_intelligence",\n',
    '    "build_predictive_forward_decision_context",\n    "build_predictive_market_intelligence",\n    "merge_forward_intelligence",\n',
)
replace_once(
    "intelligence/predictive_scenario_merge.py",
    '        currency_regime=existing.currency_regime or predictive.currency_regime,\n        schema_version="forward-intelligence.v2-predictive-market",\n',
    '        currency_regime=existing.currency_regime or predictive.currency_regime,\n        decision_context=predictive.decision_context or existing.decision_context,\n        schema_version="forward-intelligence.v2-predictive-market",\n',
)

Path("tests/test_predictive_forward_decision_context.py").write_text('''from __future__ import annotations

from types import SimpleNamespace

from committee.specialists import MarketSpecialistContext
from intelligence.forward import ForwardIntelligenceBundle
from intelligence.forward_decision import DecisionTimingPosture, EvidenceAvailability, ForwardDecisionDimension
from intelligence.predictive_market import CapitalFlowEngine, CapitalFlowObservation, build_predictive_market_intelligence, merge_forward_intelligence
from intelligence.predictive_scenario_merge import reconcile_forward_intelligence
from tests.test_production_context_assembly import AS_OF, _candidate


def _market():
    return MarketSpecialistContext(as_of=AS_OF, market_regime="constructive", expected_return_impact=0.01, confidence=0.75, trend=0.30, momentum=0.25, breadth=0.20, liquidity=0.90, positioning=0.10, evidence=("governed quote/liquidity evidence",), risks=("Liquidity can deteriorate",), entry_conditions=("Price/volume confirmation remains intact",), evidence_identifiers=("evidence:market",))


def _flow_observation(candidate):
    return CapitalFlowObservation(identifier="derived-flow:test", symbol=candidate.instrument.symbol, as_of=AS_OF, recent_volume_impulse=0.20, signed_dollar_flow=0.25, accumulation_distribution=0.22, price_volume_confirmation=0.30, persistence=0.60, short_trend=0.08, medium_trend=0.12, volatility=0.24, crowding=0.45, short_covering_likelihood=0.25, evidence_identifiers=("evidence:flow",))


def _intelligence():
    candidate = _candidate()
    result = build_predictive_market_intelligence(candidate=candidate, features=SimpleNamespace(momentum=0.15, six_month_return=0.12, twelve_month_return=0.18, annualized_volatility=0.24, rolling_annual_median=0.10), flow_observation=_flow_observation(candidate), market=_market(), existing_forward_intelligence=None)
    return candidate, result


def test_active_predictive_builder_attaches_truthful_forward_decision_context():
    candidate, intelligence = _intelligence()
    context = intelligence.forward_intelligence.decision_context
    assert context is not None
    dimensions = {item.dimension: item for item in context.dimensions}
    assert dimensions[ForwardDecisionDimension.EXPECTATIONS].availability is EvidenceAvailability.AVAILABLE
    assert dimensions[ForwardDecisionDimension.POSITIONING].availability is EvidenceAvailability.PARTIAL
    assert dimensions[ForwardDecisionDimension.MICROSTRUCTURE].availability is EvidenceAvailability.PARTIAL
    assert dimensions[ForwardDecisionDimension.REFLEXIVITY].availability is EvidenceAvailability.PARTIAL
    assert dimensions[ForwardDecisionDimension.PATH_RISK].availability is EvidenceAvailability.AVAILABLE
    assert dimensions[ForwardDecisionDimension.DERIVATIVES].availability is EvidenceAvailability.UNAVAILABLE
    assert dimensions[ForwardDecisionDimension.EARNINGS].availability is EvidenceAvailability.NOT_APPLICABLE
    assert context.timing is not None and context.timing.posture is DecisionTimingPosture.NO_TIMING_EDGE
    assert context.catalysts == ()
    assert context.thesis_monitor is not None
    assert context.thesis_monitor.invalidation_conditions == candidate.invalidation_conditions


def test_predictive_merge_paths_preserve_forward_decision_context():
    candidate, intelligence = _intelligence()
    predictive = intelligence.forward_intelligence
    existing = ForwardIntelligenceBundle(identifier="forward:existing", candidate_identifier=candidate.identifier, as_of=AS_OF, signals=(), scenarios=(), diagnostics=("existing",), model_versions=("existing.v1",))
    assert merge_forward_intelligence(existing, predictive).decision_context == predictive.decision_context
    assert reconcile_forward_intelligence(existing, predictive).decision_context == predictive.decision_context


def test_market_flow_proxy_does_not_claim_institutional_or_derivatives_coverage():
    candidate = _candidate()
    flow = CapitalFlowEngine().analyze(_flow_observation(candidate))
    assert "proxy" in flow.signal.name
    assert any("dealer inventory" in item for item in flow.signal.contradictory_evidence)
''')
