from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from operations import stage_isolated_evidence_pipeline as pipeline
import run_stage_isolated_evidence_pipeline as coordinator


def _values(tmp_path, *, max_age: str = "900") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-attempt-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": max_age,
    }


def _fail_reference(values: dict[str, str], *, requested_at: datetime):
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=requested_at,
    )
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    return pipeline.fail_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        error_type="SyntheticFailure",
        error_detail="bounded failure",
    )


def test_coordinator_supersedes_failed_attempt_and_preserves_terminal_lineage(tmp_path) -> None:
    values = _values(tmp_path)
    failed = _fail_reference(
        values,
        requested_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )

    replacement = coordinator._ensure_active_attempt(values)

    assert replacement.state == "running"
    assert replacement.pipeline_id != failed.pipeline_id
    assert replacement.completed_stages == ()
    assert replacement.next_stage == "reference"
    assert replacement.error_type is None
    assert replacement.error_detail is None
    assert replacement.evidence_as_of >= failed.evidence_as_of

    archive_path = failed.path.parent / "attempts" / f"{failed.pipeline_id}.json"
    assert archive_path.exists()
    archived = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archived["pipeline_id"] == failed.pipeline_id
    assert archived["state"] == "failed"
    assert archived["current_stage"] == "reference"
    assert archived["error_type"] == "SyntheticFailure"
    assert archived["decision_authority"] is False
    assert archived["candidate_authority"] is False
    assert archived["sizing_authority"] is False
    assert archived["construction_authority"] is False
    assert archived["execution_authority"] is False
    assert archived["paper_only"] is True
    assert archived["real_money_authorized"] is False
    assert isinstance(archived["integrity_sha256"], str)

    latest = pipeline.load_stage_isolated_evidence_state(values)
    assert latest is not None
    assert latest.pipeline_id == replacement.pipeline_id


def test_coordinator_archives_stale_failed_attempt_before_core_can_replace_it(tmp_path) -> None:
    values = _values(tmp_path, max_age="1")
    failed = _fail_reference(
        values,
        requested_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )

    replacement = coordinator._ensure_active_attempt(values)

    assert replacement.pipeline_id != failed.pipeline_id
    assert replacement.state == "running"
    archive_path = failed.path.parent / "attempts" / f"{failed.pipeline_id}.json"
    archived = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archived["pipeline_id"] == failed.pipeline_id
    assert archived["state"] == "failed"


def test_running_attempt_remains_deduplicated(tmp_path) -> None:
    values = _values(tmp_path)
    running = pipeline.ensure_stage_isolated_evidence_pipeline(values)

    observed = coordinator._ensure_active_attempt(values)

    assert observed.pipeline_id == running.pipeline_id
    assert observed.state == "running"
    assert not (running.path.parent / "attempts").exists()


def test_failed_attempt_archive_is_append_only(tmp_path) -> None:
    values = _values(tmp_path)
    failed = _fail_reference(values, requested_at=datetime.now(timezone.utc))
    archive_path = coordinator._archive_failed_attempt(failed)
    assert archive_path is not None
    original = archive_path.read_bytes()

    # Re-create a conflicting latest path for the same pipeline identity. The archive must
    # never be overwritten, even though the helper is internal and receives a validated
    # state object from the earlier read.
    failed.path.parent.mkdir(parents=True, exist_ok=True)
    failed.path.write_text("different", encoding="utf-8")

    try:
        coordinator._archive_failed_attempt(failed)
    except RuntimeError as error:
        assert "archive identity collision" in str(error)
    else:
        raise AssertionError("conflicting terminal archive must fail closed")

    assert archive_path.read_bytes() == original
