from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations import stage_isolated_evidence_pipeline as pipeline


def _values(tmp_path, *, max_age: str = "900") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-stage-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": max_age,
    }


def test_stage_pipeline_persists_canonical_prefix_and_effective_cutoff(tmp_path) -> None:
    values = _values(tmp_path)
    requested = datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=requested,
    )

    assert state.completed_stages == ()
    assert state.next_stage == "reference"

    state = pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    effective = requested + timedelta(seconds=30)
    state = pipeline.complete_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        evidence_as_of=effective,
        reference_manifest_id="manifest-1",
        reference_manifest_path=str(tmp_path / "manifest.json"),
    )

    assert state.evidence_as_of == effective
    assert state.completed_stages == ("reference",)
    assert state.next_stage == "public_live"
    assert state.reference_manifest_id == "manifest-1"

    with pytest.raises(pipeline.StageIsolatedEvidencePipelineError):
        pipeline.begin_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage="comprehensive_discovery",
        )


def test_failed_fresh_stage_resumes_same_pipeline(tmp_path) -> None:
    values = _values(tmp_path)
    requested = datetime.now(timezone.utc)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values, requested_at=requested)
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    failed = pipeline.fail_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        error_type="SyntheticFailure",
        error_detail="bounded failure",
    )

    resumed = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=requested + timedelta(seconds=30),
    )

    assert failed.state == "failed"
    assert resumed.pipeline_id == state.pipeline_id
    assert resumed.next_stage == "reference"
    assert resumed.error_type == "SyntheticFailure"


def test_stale_failed_stage_starts_new_pipeline(tmp_path) -> None:
    values = _values(tmp_path, max_age="1")
    requested = datetime.now(timezone.utc) - timedelta(seconds=10)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values, requested_at=requested)
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    pipeline.fail_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        error_type="SyntheticFailure",
        error_detail="bounded failure",
    )

    replacement = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=datetime.now(timezone.utc),
    )

    assert replacement.pipeline_id != state.pipeline_id
    assert replacement.completed_stages == ()
    assert replacement.next_stage == "reference"


def test_final_stage_requires_generation_identity(tmp_path) -> None:
    values = _values(tmp_path)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values)
    for stage in pipeline._STAGES[:-1]:
        state = pipeline.begin_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
        )
        state = pipeline.complete_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
            reference_manifest_id=("manifest-1" if stage == "reference" else None),
            reference_manifest_path=(
                str(tmp_path / "manifest.json") if stage == "reference" else None
            ),
        )

    state = pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="finalize",
    )
    with pytest.raises(pipeline.StageIsolatedEvidencePipelineError):
        pipeline.complete_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage="finalize",
        )
