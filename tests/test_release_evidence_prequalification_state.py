from __future__ import annotations

from datetime import datetime, timezone

from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)


def test_release_evidence_prequalification_round_trip(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-123",
    }
    started = datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc)

    payload = write_release_evidence_prequalification(
        values,
        state="completed",
        stage="evidence_generation_ready",
        prequalification_id="prequal-1",
        started_at=started,
        detail="qualified",
        metrics={"scheduled_lanes": 7},
        generation_id="generation-1",
    )

    loaded = load_release_evidence_prequalification(values)

    assert loaded is not None
    assert loaded["prequalification_id"] == "prequal-1"
    assert loaded["release"] == "release-123"
    assert loaded["state"] == "completed"
    assert loaded["stage"] == "evidence_generation_ready"
    assert loaded["generation_id"] == "generation-1"
    assert loaded["metrics"] == {"scheduled_lanes": 7}
    assert payload["integrity_sha256"] == loaded["integrity_sha256"]
    assert loaded["paper_only"] is True
    assert loaded["real_money_authorized"] is False


def test_release_evidence_prequalification_rejects_other_release(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-a",
    }
    write_release_evidence_prequalification(
        values,
        state="in_progress",
        stage="evidence_prequalifying",
    )

    other = dict(values)
    other["CAPITAL_INTELLIGENCE_RELEASE"] = "release-b"

    assert load_release_evidence_prequalification(other) is None
