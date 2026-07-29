from pathlib import Path


def test_production_smoke_ui_surfaces_persisted_cycle_failure() -> None:
    source = Path("production_smoke_test_ui.py").read_text(encoding="utf-8")

    assert "FROM scheduled_cycles" in source
    assert 'result["canonical_cio_cycle"] = diagnostic' in source
    assert "Canonical CIO cycle failed closed" in source
    assert "failure_detail" in source
    assert "[REDACTED]" in source
