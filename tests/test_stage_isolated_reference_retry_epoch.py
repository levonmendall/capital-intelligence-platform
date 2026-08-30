from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations import component_qualified_evidence_maintenance as maintenance
from operations import stage_isolated_evidence_pipeline as pipeline
import run_stage_isolated_evidence_pipeline as coordinator
import run_stage_isolated_evidence_stage as stage_runtime


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-retry-epoch-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


def _patch_reference_binding(monkeypatch, tmp_path, *, resumable_cutoff, observed):
    monkeypatch.setattr(
        maintenance,
        "_resumable_evidence_cutoff",
        lambda _values, *, requested: resumable_cutoff,
    )

    def _bind(_values, *, preparation_cutoff):
        observed.append(preparation_cutoff)
        return (
            SimpleNamespace(
                manifest_id="manifest-retry-epoch",
                path=tmp_path / "reference-manifest.json",
            ),
            preparation_cutoff,
        )

    monkeypatch.setattr(
        maintenance,
        "_bound_or_prepare_reference_manifest",
        _bind,
    )


def test_first_attempt_keeps_release_independent_warm_rebind(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    requested = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    warm_epoch = requested - timedelta(minutes=4)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=requested,
    )
    observed: list[datetime] = []
    _patch_reference_binding(
        monkeypatch,
        tmp_path,
        resumable_cutoff=warm_epoch,
        observed=observed,
    )

    result = stage_runtime._stage_reference(values, state)

    assert observed == [warm_epoch]
    assert result["evidence_as_of"] == warm_epoch
    assert not (state.path.parent / "attempts").exists()


def test_superseded_attempt_cannot_rebind_behind_newer_historical_snapshot(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    failed_epoch = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    first = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=failed_epoch,
    )
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=first.pipeline_id,
        stage="reference",
    )
    failed = pipeline.fail_evidence_stage(
        values,
        pipeline_id=first.pipeline_id,
        stage="reference",
        error_type="PersistentHistoricalEvidenceError",
        error_detail="persistent historical evidence was refreshed after the decision epoch",
    )
    archive = coordinator._archive_failed_attempt(failed)
    assert archive is not None
    assert archive.exists()

    replacement_epoch = failed_epoch + timedelta(minutes=8)
    historical_snapshot_epoch = failed_epoch + timedelta(minutes=3)
    replacement = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=replacement_epoch,
    )
    assert replacement.pipeline_id != first.pipeline_id
    assert replacement.evidence_as_of > historical_snapshot_epoch

    observed: list[datetime] = []
    _patch_reference_binding(
        monkeypatch,
        tmp_path,
        resumable_cutoff=failed_epoch,
        observed=observed,
    )

    result = stage_runtime._stage_reference(values, replacement)

    assert observed == [replacement_epoch]
    assert result["evidence_as_of"] == replacement_epoch
    assert result["evidence_as_of"] > historical_snapshot_epoch
