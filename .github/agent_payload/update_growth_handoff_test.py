from pathlib import Path

path = Path("tests/test_decision_process_upgrade.py")
source = path.read_text(encoding="utf-8")
old = '    assert decision.effective_opportunity_cost == pytest.approx(0.4755)\n'
new = (
    '    assert decision.effective_opportunity_cost == pytest.approx(\n'
    '        qualification.effective_opportunity_cost\n'
    '    )\n'
)
if source.count(old) != 1:
    raise RuntimeError("effective opportunity-cost handoff assertion changed")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
