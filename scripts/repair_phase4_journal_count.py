from pathlib import Path

path = Path("tests/test_canonical_cio_cycle.py")
text = path.read_text(encoding="utf-8")
old = "    assert journal.count() == 8\n"
new = "    assert journal.count() == 9\n"
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one canonical journal-count assertion, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
