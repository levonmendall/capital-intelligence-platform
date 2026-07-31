"""Remove the unsupported OPRA raw-symbol output symbology override."""

from pathlib import Path

path = Path("providers/databento_options.py")
content = path.read_text(encoding="utf-8")
old = '                    "stype_out": "raw_symbol",\n'
count = content.count(old)
if count != 1:
    raise RuntimeError(f"expected one stype_out override, found {count}")
path.write_text(content.replace(old, "", 1), encoding="utf-8")

for item in (
    Path("tools/remove_invalid_databento_stype_out.py"),
    Path(".github/workflows/remove-invalid-databento-stype-out.yml"),
):
    item.unlink(missing_ok=True)
