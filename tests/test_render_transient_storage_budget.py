"""Regression coverage for Render's bounded transient evidence-spool budget."""

from pathlib import Path
import re


_RENDER_TMP_LIMIT_MB = 2048


def _env_value(render_yaml: str, key: str) -> int:
    pattern = rf"- key: {re.escape(key)}\n\s+value: \"?(\d+)\"?"
    match = re.search(pattern, render_yaml)
    assert match is not None, f"missing Render env var: {key}"
    return int(match.group(1))


def test_render_evidence_spool_cannot_exhaust_tmp_filesystem() -> None:
    render_yaml = Path("render.yaml").read_text(encoding="utf-8")
    maximum_mb = _env_value(
        render_yaml,
        "CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_MAX_MB",
    )
    reserve_mb = _env_value(
        render_yaml,
        "CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_RESERVE_MB",
    )

    assert maximum_mb <= 1024
    assert reserve_mb >= 768
    assert maximum_mb + reserve_mb < _RENDER_TMP_LIMIT_MB


def test_render_evidence_spool_remains_transient_and_fail_closed() -> None:
    render_yaml = Path("render.yaml").read_text(encoding="utf-8")

    assert "value: /tmp/capital-intelligence/paper_evidence_spool" in render_yaml
    assert "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY" in render_yaml
    assert "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE" in render_yaml
