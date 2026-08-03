"""Regression guard for the production all-market CIO boundary."""

from __future__ import annotations

import re
from pathlib import Path

from production_context_publication_governed import (
    _comprehensive_discovery_required,
)


def test_render_requires_complete_comprehensive_discovery() -> None:
    manifest = Path("render.yaml").read_text(encoding="utf-8")
    required_setting = re.compile(
        r"(?m)^\s*- key: "
        r"CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY\s*$"
        r"\n^\s+value: [\"']?true[\"']?\s*$"
    )

    assert required_setting.search(manifest) is not None, (
        "Render must fail closed when comprehensive market discovery is unavailable; "
        "an all-market CIO evaluation cannot use a limited-scope fallback."
    )


def test_required_render_setting_activates_fail_closed_discovery(monkeypatch) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY",
        "true",
    )

    assert _comprehensive_discovery_required(probe=None, override=None) is True
