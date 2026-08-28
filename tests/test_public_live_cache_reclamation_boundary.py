from __future__ import annotations

from datetime import datetime, timezone

from operations import stage_isolated_evidence_pipeline as pipeline
import run_stage_isolated_evidence_pipeline as runtime


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-public-live-reclaim-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


class _FailingPublicLiveProcess:
    def __init__(self, command, *, events: list[tuple[object, ...]], **_kwargs) -> None:
        events.append(("spawn", str(command[2])))

    def wait(self, timeout=None) -> int:
        del timeout
        return 9


def test_completed_reference_cache_is_reclaimed_before_public_live_child(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    original = dict(values)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=datetime.now(timezone.utc),
    )
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    pipeline.complete_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        reference_manifest_id="manifest-test",
        reference_manifest_path=str(tmp_path / "reference-manifest.json"),
    )

    events: list[tuple[object, ...]] = []

    def _reclaim(_values, **kwargs) -> None:
        events.append(
            (
                "reclaim",
                kwargs["stage"],
                kwargs["event"],
                kwargs["code"],
                kwargs["capture_report"],
            )
        )

    monkeypatch.setattr(runtime, "_run_completed_evidence_cache_reclamation", _reclaim)
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda command, **kwargs: _FailingPublicLiveProcess(
            command,
            events=events,
            **kwargs,
        ),
    )

    assert runtime.run_pipeline(values) == 9
    assert events == [
        (
            "reclaim",
            "public_live",
            "stage_isolated_public_live_cache_reclamation",
            runtime._COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE,
            True,
        ),
        ("spawn", "public_live"),
    ]
    assert values == original

    latest = pipeline.load_stage_isolated_evidence_state(values)
    assert latest is not None
    assert latest.completed_stages == ("reference",)
    assert latest.next_stage == "public_live"
