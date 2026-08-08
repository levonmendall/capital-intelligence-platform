"""Focused regressions for the Render runtime-workspace bootstrap."""

from pathlib import Path

from run_render_service_workspace import prepare_runtime_workspace


def test_workspace_is_created_before_tempfile_users_start(tmp_path) -> None:
    workspace = tmp_path / "runtime_transient"

    prepared = prepare_runtime_workspace({"TMPDIR": str(workspace)})

    assert prepared == workspace
    assert workspace.is_dir()


def test_workspace_cleanup_removes_only_disposable_backup_staging(tmp_path) -> None:
    workspace = tmp_path / "runtime_transient"
    workspace.mkdir()
    abandoned_backup = workspace / "capital-intelligence-backup-old"
    abandoned_verify = workspace / "capital-intelligence-verify-old"
    abandoned_restore = workspace / "capital-intelligence-restore-old"
    evidence_spool = workspace / "paper_evidence_spool"
    unrelated = workspace / "canonical-looking-do-not-delete"
    symlink_target = tmp_path / "outside"
    symlink_target.mkdir()
    symlink = workspace / "capital-intelligence-backup-link"

    for directory in (
        abandoned_backup,
        abandoned_verify,
        abandoned_restore,
        evidence_spool,
        unrelated,
    ):
        directory.mkdir()
        (directory / "sentinel").write_text("preserve semantics", encoding="utf-8")
    symlink.symlink_to(symlink_target, target_is_directory=True)

    prepare_runtime_workspace({"TMPDIR": str(workspace)})

    assert not abandoned_backup.exists()
    assert not abandoned_verify.exists()
    assert not abandoned_restore.exists()
    assert evidence_spool.exists()
    assert unrelated.exists()
    assert symlink.is_symlink()
    assert symlink_target.exists()


def test_workspace_requires_explicit_tmpdir() -> None:
    try:
        prepare_runtime_workspace({})
    except RuntimeError as error:
        assert "TMPDIR" in str(error)
    else:
        raise AssertionError("missing TMPDIR must fail closed")
