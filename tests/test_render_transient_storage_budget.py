"""Regression coverage for Render's bounded disposable evidence-spool budget."""

from pathlib import Path
import re


_RENDER_PERSISTENT_DISK_MB = 10 * 1024


def _env_value(render_yaml: str, key: str) -> int:
    pattern = rf"- key: {re.escape(key)}\n\s+value: \"?(\d+)\"?"
    match = re.search(pattern, render_yaml)
    assert match is not None, f"missing Render env var: {key}"
    return int(match.group(1))


def test_render_evidence_spool_uses_bounded_non_authority_persistent_working_dir() -> None:
    render_yaml = Path("render.yaml").read_text(encoding="utf-8")
    maximum_mb = _env_value(
        render_yaml,
        "CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_MAX_MB",
    )
    reserve_mb = _env_value(
        render_yaml,
        "CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_RESERVE_MB",
    )

    assert (
        "value: /app/database/runtime_transient/paper_evidence_spool"
        in render_yaml
    )
    assert "value: /tmp/capital-intelligence/paper_evidence_spool" not in render_yaml
    assert maximum_mb <= 4096
    assert reserve_mb >= 1024
    assert maximum_mb + reserve_mb < _RENDER_PERSISTENT_DISK_MB


def test_render_evidence_spool_remains_disposable_and_fail_closed() -> None:
    render_yaml = Path("render.yaml").read_text(encoding="utf-8")

    assert "cycle-local, disposable working files" in render_yaml
    assert "not canonical state" in render_yaml
    assert "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY" in render_yaml
    assert "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE" in render_yaml
