from pathlib import Path

path = Path("tests/test_production_smoke_test.py")
source = path.read_text(encoding="utf-8")
old = '''                "report_state": "no_transaction_recommended",
                "execution_state": "idle",
'''
new = '''                "report_state": "no_transaction_recommended",
                "cio_briefing_status": "no_superior_opportunity",
                "safe_abstention_recorded": True,
                "comparative_cio_decision_complete": True,
                "execution_state": "idle",
'''
if source.count(old) != 1:
    raise RuntimeError(f"expected one smoke report fixture, found {source.count(old)}")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
