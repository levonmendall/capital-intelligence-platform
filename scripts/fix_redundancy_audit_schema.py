from pathlib import Path

for path in (
    Path("providers/redundancy_audit.py"),
    Path("tests/test_all_asset_redundancy_v2.py"),
    Path("tests/test_all_asset_redundancy_integration.py"),
):
    text = path.read_text(encoding="utf-8")
    old = "credential_values_included"
    if old not in text:
        raise SystemExit(f"expected audit schema key missing in {path}")
    path.write_text(text.replace(old, "secret_values_included"), encoding="utf-8")
