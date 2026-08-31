from __future__ import annotations

from operations.stage_owner_lease import try_acquire_stage_owner


def test_exact_stage_owner_lease_blocks_overlapping_coordinator(tmp_path) -> None:
    state_path = tmp_path / "release" / "stage-isolated-evidence-latest.json"
    first = try_acquire_stage_owner(
        state_path,
        pipeline_id="pipeline-1",
        stage="comprehensive_discovery",
    )
    assert first is not None
    try:
        assert (
            try_acquire_stage_owner(
                state_path,
                pipeline_id="pipeline-1",
                stage="comprehensive_discovery",
            )
            is None
        )
    finally:
        first.release()

    second = try_acquire_stage_owner(
        state_path,
        pipeline_id="pipeline-1",
        stage="comprehensive_discovery",
    )
    assert second is not None
    second.release()
