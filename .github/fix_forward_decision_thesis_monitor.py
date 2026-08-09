from pathlib import Path

path = Path("intelligence/predictive_market.py")
text = path.read_text()
old_import = '''    ThesisMonitor,\n    build_forward_decision_context,\n)\n'''
new_import = '''    ThesisMonitor,\n    applicable_dimensions,\n    build_forward_decision_context,\n)\n'''
if text.count(old_import) != 1:
    raise SystemExit("forward-decision import patch target mismatch")
text = text.replace(old_import, new_import, 1)
old_return = '''    return build_forward_decision_context(\n        identifier=f"forward-decision:{candidate_identifier}:{as_of.isoformat()}",\n'''
new_return = '''    applicable = applicable_dimensions(asset_class)\n    assessments = [\n        item for item in assessments if item.dimension in applicable\n    ]\n    return build_forward_decision_context(\n        identifier=f"forward-decision:{candidate_identifier}:{as_of.isoformat()}",\n'''
if text.count(old_return) != 1:
    raise SystemExit("forward-decision applicability patch target mismatch")
path.write_text(text.replace(old_return, new_return, 1))

test_path = Path("tests/test_predictive_forward_decision_context.py")
test = test_path.read_text()
if "from dataclasses import replace\n" not in test:
    test = test.replace(
        "from types import SimpleNamespace\n",
        "from dataclasses import replace\nfrom types import SimpleNamespace\n",
        1,
    )
if "from cio import CandidateAssetClass\n" not in test:
    test = test.replace(
        "from committee.specialists import MarketSpecialistContext\n",
        "from cio import CandidateAssetClass\nfrom committee.specialists import MarketSpecialistContext\n",
        1,
    )
regression = '''

def test_cash_equivalent_filters_non_applicable_predictive_dimensions():
    base = _candidate()
    candidate = replace(
        base,
        instrument=replace(
            base.instrument,
            asset_class=CandidateAssetClass.CASH_EQUIVALENT,
        ),
    )
    result = build_predictive_market_intelligence(
        candidate=candidate,
        features=SimpleNamespace(
            momentum=0.15,
            six_month_return=0.12,
            twelve_month_return=0.18,
            annualized_volatility=0.24,
            rolling_annual_median=0.10,
        ),
        flow_observation=_flow_observation(candidate),
        market=_market(),
        existing_forward_intelligence=None,
    )
    context = result.forward_intelligence.decision_context
    assert context is not None
    dimensions = {item.dimension: item for item in context.dimensions}
    assert dimensions[ForwardDecisionDimension.EXPECTATIONS].availability is EvidenceAvailability.AVAILABLE
    assert dimensions[ForwardDecisionDimension.CATALYSTS].availability is EvidenceAvailability.NOT_APPLICABLE
    assert dimensions[ForwardDecisionDimension.POSITIONING].availability is EvidenceAvailability.NOT_APPLICABLE
    assert dimensions[ForwardDecisionDimension.MICROSTRUCTURE].availability is EvidenceAvailability.NOT_APPLICABLE
    assert dimensions[ForwardDecisionDimension.REFLEXIVITY].availability is EvidenceAvailability.NOT_APPLICABLE
'''
if "test_cash_equivalent_filters_non_applicable_predictive_dimensions" not in test:
    test += regression
test_path.write_text(test)
