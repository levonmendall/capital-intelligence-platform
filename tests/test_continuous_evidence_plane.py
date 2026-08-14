from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    load_latest_evidence_plane,
    refresh_continuous_evidence_plane,
)


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "test-release",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


def _qualified_generation(tmp_path: Path, *, as_of: datetime):
    calls = {"reference": 0, "public": 0, "discovery": 0}

    def reference(values):
        assert values["CAPITAL_INTELLIGENCE_DATA_DIR"] == str(tmp_path)
        calls["reference"] += 1
        return SimpleNamespace(manifest_id="reference:test")

    def public(timestamp):
        assert timestamp == as_of
        calls["public"] += 1
        return SimpleNamespace(state="available")

    def discovery(timestamp):
        assert timestamp == as_of
        calls["discovery"] += 1
        return object()

    generation = refresh_continuous_evidence_plane(
        as_of=as_of,
        values=_values(tmp_path),
        reference_preparer=reference,
        public_collector=public,
        discovery=discovery,
    )
    return generation, calls


def test_qualified_background_generation_can_freeze_later_pit_snapshot_without_refresh(
    tmp_path: Path,
) -> None:
    as_of = datetime.now(timezone.utc) - timedelta(minutes=2)
    generation, calls = _qualified_generation(tmp_path, as_of=as_of)

    cutoff = as_of + timedelta(minutes=1)
    snapshot = ensure_point_in_time_snapshot(
        cutoff=cutoff,
        values=_values(tmp_path),
        allow_refresh=False,
    )

    assert calls == {"reference": 1, "public": 1, "discovery": 1}
    assert snapshot.cutoff == cutoff
    assert snapshot.plane_generation_id == generation.generation_id
    assert snapshot.plane_as_of == as_of
    assert snapshot.reference_manifest_id == "reference:test"
    assert snapshot.path.exists()
    payload = json.loads(snapshot.path.read_text(encoding="utf-8"))
    assert payload["raw_evidence_duplicated"] is False
    assert payload["point_in_time_enforced"] is True
    assert payload["investment_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_stale_plane_fails_closed_when_refresh_is_not_allowed(tmp_path: Path) -> None:
    as_of = datetime.now(timezone.utc) - timedelta(hours=2)
    _qualified_generation(tmp_path, as_of=as_of)

    with pytest.raises(
        ContinuousEvidencePlaneError,
        match="missing or stale",
    ):
        ensure_point_in_time_snapshot(
            cutoff=datetime.now(timezone.utc),
            values=_values(tmp_path),
            allow_refresh=False,
        )


def test_tampered_generation_fails_integrity_check(tmp_path: Path) -> None:
    as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
    _qualified_generation(tmp_path, as_of=as_of)
    path = tmp_path / "continuous_evidence_plane" / "latest-qualified.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reference_manifest_id"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContinuousEvidencePlaneError, match="integrity mismatch"):
        load_latest_evidence_plane(_values(tmp_path))


def test_future_evidence_cutoff_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ContinuousEvidencePlaneError, match="future cutoff"):
        refresh_continuous_evidence_plane(
            as_of=datetime.now(timezone.utc) + timedelta(hours=1),
            values=_values(tmp_path),
            reference_preparer=lambda values: SimpleNamespace(manifest_id="unused"),
            public_collector=lambda timestamp: SimpleNamespace(state="available"),
            discovery=lambda timestamp: object(),
        )


def test_failed_public_refresh_cannot_publish_qualified_plane(tmp_path: Path) -> None:
    as_of = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(ContinuousEvidencePlaneError, match="public live information"):
        refresh_continuous_evidence_plane(
            as_of=as_of,
            values=_values(tmp_path),
            reference_preparer=lambda values: SimpleNamespace(manifest_id="reference:test"),
            public_collector=lambda timestamp: SimpleNamespace(state="failed"),
            discovery=lambda timestamp: object(),
        )

    assert not (
        tmp_path / "continuous_evidence_plane" / "latest-qualified.json"
    ).exists()


def test_memory_safe_render_supervisor_defers_noncritical_evidence_coordinator() -> None:
    import run_render_service_memory_safe as runtime

    specs = runtime.memory_safe_managed_processes(
        port=8501,
        python_executable="python",
    )
    matching = tuple(item for item in specs if item.name == "continuous-evidence-plane")
    assert len(matching) == 1
    spec = matching[0]
    assert spec.command == ("python", "run_bounded_continuous_evidence_plane.py")
    assert spec.critical is False
    assert spec.restart_delay_seconds == 60
