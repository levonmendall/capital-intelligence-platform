from pathlib import Path

path = Path("intelligence/predictive_market.py")
text = path.read_text()
old = '''    thesis_monitor = ThesisMonitor(
        thesis="Governed candidate thesis: " + "; ".join(catalysts[:2]),
        must_remain_true=tuple(getattr(candidate, "critical_assumptions", ()) or ()),
        invalidation_conditions=tuple(getattr(candidate, "invalidation_conditions", ()) or ()),
        monitor_evidence=tuple(getattr(candidate, "monitoring_indicators", ()) or ()),
    )
'''
new = '''    invalidation_conditions = tuple(
        getattr(candidate, "invalidation_conditions", ()) or ()
    )
    thesis_monitor = (
        None
        if not invalidation_conditions
        else ThesisMonitor(
            thesis="Governed candidate thesis: " + "; ".join(catalysts[:2]),
            must_remain_true=tuple(
                getattr(candidate, "critical_assumptions", ()) or ()
            ),
            invalidation_conditions=invalidation_conditions,
            monitor_evidence=tuple(
                getattr(candidate, "monitoring_indicators", ()) or ()
            ),
        )
    )
'''
if text.count(old) != 1:
    raise SystemExit("thesis monitor patch target mismatch")
path.write_text(text.replace(old, new, 1))

test_path = Path("tests/test_predictive_forward_decision_context.py")
test = test_path.read_text()
if "from dataclasses import replace\n" not in test:
    test = test.replace(
        "from types import SimpleNamespace\n",
        "from dataclasses import replace\nfrom types import SimpleNamespace\n",
        1,
    )
regression = '''

def test_candidate_without_explicit_invalidation_is_not_dropped_by_advisory_v2():
    candidate = replace(_candidate(), invalidation_conditions=())
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
    assert result.forward_intelligence.decision_context is not None
    assert result.forward_intelligence.decision_context.thesis_monitor is None
'''
if "test_candidate_without_explicit_invalidation_is_not_dropped_by_advisory_v2" not in test:
    test += regression
test_path.write_text(test)
