from __future__ import annotations

from datetime import datetime, timezone

from operations.certification_runtime_state import (
    advance_linear_state_for_cutoff,
    certification_runtime_enabled,
)
from operations.certification_state_machine import CertificationState


CUTOFF = datetime(2026, 8, 19, 23, 30, tzinfo=timezone.utc)


def _production_values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "RENDER_GIT_COMMIT": "release-test",
    }


def test_render_capability_cio_does_not_require_all_market_lineage(monkeypatch, tmp_path):
    values = {
        **_production_values(tmp_path),
        "RENDER": "true",
    }

    assert certification_runtime_enabled(values) is False
    assert (
        advance_linear_state_for_cutoff(
            cutoff=CUTOFF,
            target=CertificationState.SCREENING_COMPLETE,
            source_id="capability-screening:test",
            values=values,
        )
        is None
    )


def test_explicit_capability_mode_is_decoupled_outside_render(tmp_path):
    values = {
        **_production_values(tmp_path),
        "CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION": "true",
    }

    assert certification_runtime_enabled(values) is False


def test_explicit_comprehensive_mode_retains_strict_all_market_runtime(tmp_path):
    values = {
        **_production_values(tmp_path),
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION": "false",
    }

    assert certification_runtime_enabled(values) is True
