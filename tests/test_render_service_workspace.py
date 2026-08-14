"""Focused regressions for the Render runtime-workspace bootstrap."""

import json
from pathlib import Path
from types import SimpleNamespace

import run_render_service_workspace
from run_render_service_workspace import prepare_runtime_workspace


def _no_projected_headroom() -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_REFERENCE_PUBLISH_HEADROOM_MB": "0",
        "CAPITAL_INTELLIGENCE_RUNTIME_WORKSPACE_HEADROOM_MB": "0",
    }


def test_workspace_is_created_before_tempfile_users_start(tmp_path) -> None:
    workspace = tmp_path / "runtime_transient"

    prepared = prepare_runtime_workspace({"TMPDIR": str(workspace)})

    assert prepared == workspace
    assert workspace.is_dir()


def test_workspace_cleanup_reclaims_all_non_symlink_disposable_contents(tmp_path) -> None:
    workspace = tmp_path / "runtime_transient"
    workspace.mkdir()
    abandoned_backup = workspace / "capital-intelligence-backup-old"
    abandoned_verify = workspace / "capital-intelligence-verify-old"
    abandoned_restore = workspace / "capital-intelligence-restore-old"
    evidence_spool = workspace / "paper_evidence_spool"
    unrelated_scratch = workspace / "old-provider-scratch"
    stale_file = workspace / "partial-download.tmp"
    symlink_target = tmp_path / "outside"
    symlink_target.mkdir()
    symlink = workspace / "external-link"

    for directory in (
        abandoned_backup,
        abandoned_verify,
        abandoned_restore,
        evidence_spool,
        unrelated_scratch,
    ):
        directory.mkdir()
        (directory / "sentinel").write_text("disposable", encoding="utf-8")
    stale_file.write_text("disposable", encoding="utf-8")
    symlink.symlink_to(symlink_target, target_is_directory=True)

    prepare_runtime_workspace({"TMPDIR": str(workspace)})

    assert not abandoned_backup.exists()
    assert not abandoned_verify.exists()
    assert not abandoned_restore.exists()
    assert not evidence_spool.exists()
    assert not unrelated_scratch.exists()
    assert not stale_file.exists()
    assert symlink.is_symlink()
    assert symlink_target.exists()


def test_reference_cleanup_reclaims_only_superseded_release_bindings(tmp_path) -> None:
    workspace = tmp_path / "runtime_transient"
    data_root = tmp_path / "data"
    reference_root = data_root / "reference_readiness"
    components = reference_root / "assets" / "crypto"
    components.mkdir(parents=True)

    stale_manifest = reference_root / "instrument-master-old-release.json"
    stale_progress = reference_root / "progress-old-release.json"
    current_manifest = reference_root / "instrument-master-current_release.json"
    current_progress = reference_root / "progress-current_release.json"
    aggregate_component = reference_root / "eodhd_directories-latest-qualified.json"
    lane_component = components / "catalog-latest-qualified.json"
    interrupted_write = reference_root / "eodhd_directories-latest-qualified.json.tmp"
    nested_interrupted_write = components / "catalog-latest-qualified.json.tmp"

    for path in (
        stale_manifest,
        stale_progress,
        current_manifest,
        current_progress,
        aggregate_component,
        lane_component,
        interrupted_write,
        nested_interrupted_write,
    ):
        path.write_text(path.name, encoding="utf-8")

    environment = {
        "TMPDIR": str(workspace),
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root),
        "RENDER_GIT_COMMIT": "current_release",
        "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1",
        **_no_projected_headroom(),
    }
    prepare_runtime_workspace(environment)

    assert not stale_manifest.exists()
    assert not stale_progress.exists()
    assert current_manifest.exists()
    assert current_progress.exists()
    assert aggregate_component.exists()
    assert lane_component.exists()
    assert not interrupted_write.exists()
    assert not nested_interrupted_write.exists()
    telemetry = json.loads(environment["CAPITAL_INTELLIGENCE_STORAGE_PREFLIGHT_JSON"])
    assert telemetry["workspace_shared_filesystem"] is True
    assert telemetry["required_free_mb"] == 1


def test_reference_cleanup_preserves_release_bindings_without_identity(tmp_path) -> None:
    workspace = tmp_path / "runtime_transient"
    data_root = tmp_path / "data"
    reference_root = data_root / "reference_readiness"
    reference_root.mkdir(parents=True)
    manifest = reference_root / "instrument-master-unknown-release.json"
    progress = reference_root / "progress-unknown-release.json"
    interrupted_write = reference_root / "progress-unknown-release.json.tmp"
    manifest.write_text("manifest", encoding="utf-8")
    progress.write_text("progress", encoding="utf-8")
    interrupted_write.write_text("scratch", encoding="utf-8")

    prepare_runtime_workspace(
        {
            "TMPDIR": str(workspace),
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root),
            "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1",
            **_no_projected_headroom(),
        }
    )

    assert manifest.exists()
    assert progress.exists()
    assert not interrupted_write.exists()


def test_storage_preflight_is_published_for_runtime_diagnostics(
    tmp_path, monkeypatch, capsys
) -> None:
    workspace = tmp_path / "runtime_transient"
    data_root = tmp_path / "data"
    snapshot = SimpleNamespace(
        telemetry=lambda: {
            "filesystem_total_mb": 25600,
            "filesystem_free_mb": 20480,
            "required_free_mb": 7168,
            "workspace_shared_filesystem": True,
        }
    )
    monkeypatch.setattr(
        run_render_service_workspace,
        "preflight_storage_capacity",
        lambda _environment: snapshot,
    )
    environment = {
        "TMPDIR": str(workspace),
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root),
    }

    prepare_runtime_workspace(environment)

    payload = json.loads(environment["CAPITAL_INTELLIGENCE_STORAGE_PREFLIGHT_JSON"])
    assert payload["filesystem_total_mb"] == 25600
    assert payload["filesystem_free_mb"] == 20480
    assert payload["required_free_mb"] == 7168
    assert "[storage-governance]" in capsys.readouterr().out


def test_workspace_requires_explicit_tmpdir() -> None:
    try:
        prepare_runtime_workspace({})
    except RuntimeError as error:
        assert "TMPDIR" in str(error)
    else:
        raise AssertionError("missing TMPDIR must fail closed")
