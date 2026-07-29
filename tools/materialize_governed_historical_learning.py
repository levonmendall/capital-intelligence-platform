from pathlib import Path

path = Path("cio/historical_learning.py")
source = path.read_text(encoding="utf-8")
old = "            position_size_multiplier=0.50,\n            confidence_ceiling=0.65,"
new = "            position_size_multiplier=1.0,\n            confidence_ceiling=0.65,"
if old not in source:
    raise RuntimeError("unavailable historical-learning sizing anchor missing")
path.write_text(source.replace(old, new, 1), encoding="utf-8")

test_path = Path("tests/test_governed_historical_learning.py")
test_source = test_path.read_text(encoding="utf-8")
old_test = "    assert context.position_size_multiplier == 0.50\n"
new_test = "    assert context.position_size_multiplier == 1.0\n"
if old_test not in test_source:
    raise RuntimeError("future-manifest sizing assertion anchor missing")
test_path.write_text(test_source.replace(old_test, new_test, 1), encoding="utf-8")
