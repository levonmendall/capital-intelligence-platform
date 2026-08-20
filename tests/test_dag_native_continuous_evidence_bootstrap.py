"""Regression coverage for the production continuous-evidence DAG bootstrap."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import run_bounded_continuous_evidence_plane as bounded


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_bounded_continuous_evidence_uses_stage_isolated_entrypoint() -> None:
    assert bounded._SPEC.script == "run_stage_isolated_evidence_pipeline.py"
    assert bounded._SPEC.arguments == ()
    assert bounded._SPEC.default_timeout_seconds == 3600.0


def test_fresh_evidence_interpreter_installs_all_dag_native_seams_before_owner_import() -> None:
    code = """
from run_dag_native_continuous_evidence_plane import install_and_verify_dag_native_runtime
install_and_verify_dag_native_runtime()
from operations import authoritative_comprehensive_discovery as authoritative
from operations import component_qualified_evidence_maintenance as maintenance
from operations import persistent_certification_scheduler as scheduler
assert getattr(maintenance._supervised_discovery_runner, '_dag_native_supervision', False) is True
assert getattr(scheduler.PersistentCertificationScheduler.run, '_dag_native_supervision', False) is True
assert getattr(authoritative._acquire, '_spawn_safe_authoritative_acquisition', False) is True
"""
    completed = subprocess.run(
        (sys.executable, "-c", code),
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout