from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import qualified_evidence_maintenance as maintenance


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


def test_maintenance_reuses_current_exact_manifest_and_archives_generation(
    tmp_path: Path,
) -> None:
    values = _values(tmp_path)
    manifest_path = tmp_path / "reference.json"
    manifest_path.write_text("{}", encoding="utf-8")
    calls = {"reference": 0, "public": 0, "discovery": 0}

    def reference(resolved):
        assert resolved["CAPITAL_INTELLIGENCE_RELEASE"] == "release-test"
        calls["reference"] += 1
        return SimpleNamespace(manifest_id="manifest:test", path=manifest_path)

    def public(timestamp):
        assert timestamp.tzinfo is not None
        calls["public"] += 1
        return SimpleNamespace(state="available", required_sources_ready=True)

    def discovery(timestamp):
        assert timestamp.tzinfo is not None
        assert maintenance.os.environ[
            "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
        ] == str(manifest_path)
        assert maintenance.os.environ[
            "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
        ] == "manifest:test"
        calls["discovery"] += 1
        return object()

    first = maintenance.maintain_continuous_evidence_plane(
        values=values,
        reference_preparer=reference,
        public_collector=public,
        discovery=discovery,
    )
    second = maintenance.maintain_continuous_evidence_plane(
        values=values,
        reference_preparer=reference,
        public_collector=public,
        discovery=discovery,
    )

    assert first.state == "refreshed"
    assert first.refreshed is True
    assert first.preparation_passes == 1
    assert first.archived_generation_path.exists()
    assert first.archived_generation_path.name == f"{first.generation.generation_id}.json"
    assert second.state == "current"
    assert second.refreshed is False
    assert second.generation.generation_id == first.generation.generation_id
    assert calls == {"reference": 2, "public": 1, "discovery": 1}


def test_default_public_maintenance_honors_collection_cadence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import public_live_collection_runtime

    values = _values(tmp_path)
    observed: dict[str, object] = {}

    def collect(*, now, force):
        observed["now"] = now
        observed["force"] = force
        return SimpleNamespace(state="available", required_sources_ready=True)

    monkeypatch.setattr(
        public_live_collection_runtime,
        "collect_public_live_information_if_due",
        collect,
    )
    result = maintenance.maintain_continuous_evidence_plane(
        values=values,
        reference_preparer=lambda resolved: SimpleNamespace(manifest_id="manifest:test"),
        discovery=lambda timestamp: object(),
    )

    assert result.refreshed is True
    assert observed["force"] is False


def test_prequalified_reference_loader_is_disk_only_and_binds_snapshot_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values = _values(tmp_path)
    reference_root = tmp_path / "reference_readiness"
    reference_root.mkdir(parents=True)
    path = reference_root / "instrument-master-release-test.json"
    captured = datetime.now(timezone.utc)
    path.write_text(
        json.dumps(
            {
                "manifest_id": "manifest:test",
                "release": "release-test",
                "captured_at": captured.isoformat(),
                "config_fingerprint": "config:test",
                "eodhd_exchanges": ["US"],
                "futures_roots": ["ES"],
            }
        ),
        encoding="utf-8",
    )
    snapshot = SimpleNamespace(
        cutoff=captured,
        reference_manifest_id="manifest:test",
    )
    monkeypatch.setattr(
        maintenance._plane,
        "ensure_point_in_time_snapshot",
        lambda **kwargs: snapshot,
    )
    monkeypatch.setattr(
        maintenance,
        "load_reference_catalogs",
        lambda **kwargs: {CandidateAssetClass.INTERNATIONAL_EQUITY: (object(), object())},
    )

    manifest = maintenance.load_prequalified_reference_manifest(values)

    assert manifest.manifest_id == "manifest:test"
    assert manifest.release == "release-test"
    assert manifest.catalog_counts == ((CandidateAssetClass.INTERNATIONAL_EQUITY.value, 2),)
    assert values["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"] == str(path)
    assert values["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"] == "manifest:test"


def test_release_diagnostic_executor_prequalifies_evidence_first(monkeypatch) -> None:
    import run_render_service_memory_safe as runtime

    events: list[tuple[str, object]] = []

    def run(command, *, env, check):
        assert check is False
        events.append(("evidence", tuple(command)))
        return SimpleNamespace(returncode=0)

    def diagnostic(command, *, diagnostic_values, refresh_seconds):
        events.append(("diagnostic", tuple(command)))
        return 0

    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "_ORIGINAL_RELEASE_DIAGNOSTIC_EXECUTOR", diagnostic)
    result = runtime._run_release_diagnostic_with_prequalified_evidence(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values={"CAPITAL_INTELLIGENCE_RELEASE": "release-test"},
    )

    assert result == 0
    assert events[0][0] == "evidence"
    assert events[0][1][-2:] == ("run_bounded_continuous_evidence_plane.py", "--once")
    assert events[1] == (
        "diagnostic",
        ("python", "run_bounded_manual_cio_diagnostic.py"),
    )


def test_bounded_evidence_coordinator_supports_one_shot(monkeypatch) -> None:
    import run_bounded_continuous_evidence_plane as runtime

    observed: dict[str, object] = {}

    def isolated(spec, *, values, lane_wait_seconds):
        observed["name"] = spec.name
        observed["arguments"] = spec.arguments
        observed["wait"] = lane_wait_seconds
        return 0

    monkeypatch.setattr(runtime, "_run_isolated_once", isolated)
    result = runtime.run_continuous_once(
        {
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MEMORY_LANE_WAIT_SECONDS": "45",
        }
    )

    assert result == 0
    assert observed == {
        "name": "continuous-evidence-plane",
        "arguments": ("--once",),
        "wait": 45.0,
    }
