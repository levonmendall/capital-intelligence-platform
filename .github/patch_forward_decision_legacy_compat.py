from pathlib import Path

path = Path("intelligence/predictive_market.py")
text = path.read_text()
old_import = '''from committee.specialists import MarketSpecialistContext\n'''
new_import = '''from cio.models import CandidateDecisionRecord\nfrom committee.specialists import MarketSpecialistContext\n'''
if text.count(old_import) != 1:
    raise SystemExit("candidate record import target mismatch")
text = text.replace(old_import, new_import, 1)
old_context = '''    decision_context = build_predictive_forward_decision_context(\n        candidate=candidate,\n        flow=flow,\n        expectations=expectations,\n        market=enriched_market,\n        existing_forward_intelligence=existing_forward_intelligence,\n    )\n    predictive_bundle = ForwardIntelligenceBundle(\n'''
new_context = '''    decision_context = (\n        build_predictive_forward_decision_context(\n            candidate=candidate,\n            flow=flow,\n            expectations=expectations,\n            market=enriched_market,\n            existing_forward_intelligence=existing_forward_intelligence,\n        )\n        if isinstance(candidate, CandidateDecisionRecord)\n        else None\n    )\n    predictive_bundle = ForwardIntelligenceBundle(\n'''
if text.count(old_context) != 1:
    raise SystemExit("decision context construction target mismatch")
text = text.replace(old_context, new_context, 1)
old_versions = '''        model_versions=(CapitalFlowEngine.version, MarketExpectationsEngine.version, decision_context.schema_version),\n        decision_context=decision_context,\n'''
new_versions = '''        model_versions=(\n            CapitalFlowEngine.version,\n            MarketExpectationsEngine.version,\n            *((decision_context.schema_version,) if decision_context is not None else ()),\n        ),\n        decision_context=decision_context,\n'''
if text.count(old_versions) != 1:
    raise SystemExit("model versions target mismatch")
path.write_text(text.replace(old_versions, new_versions, 1))

test_path = Path("tests/test_predictive_market_intelligence.py")
test = test_path.read_text()
needle = '''    assert "predictive-market" in result.forward_intelligence.identifier\n'''
replacement = '''    assert "predictive-market" in result.forward_intelligence.identifier\n    assert result.forward_intelligence.decision_context is None\n'''
if test.count(needle) != 1:
    raise SystemExit("legacy compatibility assertion target mismatch")
test_path.write_text(test.replace(needle, replacement, 1))
