from __future__ import annotations

from datetime import datetime, timezone

import pytest

from operations.manual_cio_diagnostic import ManualCIODiagnosticRequest
from operations.release_production_state import (
    load_release_production_state,
    publish_release_production_state,
    release_production_state_path,
)


NOW = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)


def _request(release: str) -> ManualCIODiagnosticRequest:
    return ManualCIODiagnosticRequest(
        request_id="request-release-state",
        requested_at=NOW,
        requested_by=f"render-release:{release}",
    )


def test_exact_release_state_round_trips_independently_of_global_pointer(tmp_path):
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH": str(tmp_path / "global.json")
    }
    release = "abc123def456"
    request = _request(release)

    path = publish_release_production_state(release, request, values=values)
    loaded = load_release_production_state(release, values=values)

    assert path == release_production_state_path(release, values=values)
    assert loaded == request
    assert path != tmp_path / "global.json"


def test_release_state_rejects_cross_release_requester(tmp_path):
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH": str(tmp_path / "global.json")
    }

    with pytest.raises(ValueError, match="requester"):
        publish_release_production_state(
            "current123",
            _request("prior456"),
            values=values,
        )

    assert load_release_production_state("current123", values=values) is None


def test_release_state_fails_closed_for_invalid_release_identifier(tmp_path):
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH": str(tmp_path / "global.json")
    }

    assert release_production_state_path("../escape", values=values) is None
    assert load_release_production_state("unknown", values=values) is None
