from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import capture_render_production_telemetry_resilient as resilient
from scripts import render_telemetry_commit_status as commit_status


def _snapshot(*, release_matches_expected: bool = False) -> dict[str, object]:
    return {
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "capture_state": "ok",
        "expected_release": "expected-main-sha",
        "failure_class": "release_mismatch" if not release_matches_expected else "terminal_failure",
        "diagnostic": {
            "release_matches_expected": release_matches_expected,
            "state": "failed" if release_matches_expected else "pending",
            "stage": "evidence_prequalification_failed" if release_matches_expected else "release_wait",
            "elapsed_seconds": 1,
            "all_market_evaluation_complete": False,
        },
    }


def test_scheduled_safe_release_mismatch_is_awaiting_deployment_success() -> None:
    state, description = commit_status.status_for_snapshot(
        _snapshot(), allow_awaiting_deployment=True
    )

    assert state == "success"
    assert description == "awaiting deployment of expected production release"


def test_release_mismatch_remains_non_success_without_schedule_opt_in() -> None:
    state, _ = commit_status.status_for_snapshot(_snapshot())

    assert state != "success"


def test_schedule_opt_in_cannot_bypass_credential_safety() -> None:
    snapshot = _snapshot()
    snapshot["credential_safe"] = False

    with pytest.raises(commit_status.InvalidTelemetrySnapshot):
        commit_status.status_for_snapshot(snapshot, allow_awaiting_deployment=True)


def test_schedule_opt_in_cannot_hide_exact_release_terminal_failure() -> None:
    state, _ = commit_status.status_for_snapshot(
        _snapshot(release_matches_expected=True), allow_awaiting_deployment=True
    )

    assert state == "error"


def test_wrapper_converts_only_opted_in_safe_release_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "telemetry.json"
    forwarded: list[str] = []

    def fake_main(arguments: object) -> int:
        assert arguments is not None
        forwarded.extend(str(value) for value in arguments)
        output.write_text(json.dumps(_snapshot()), encoding="utf-8")
        return resilient._base._EXIT_RELEASE_MISMATCH

    monkeypatch.setattr(resilient._base, "main", fake_main)

    code = resilient.main(
        [
            "--url",
            "https://example.invalid/telemetry.json",
            "--expected-release",
            "expected-main-sha",
            "--output",
            str(output),
            "--allow-awaiting-deployment",
        ]
    )

    rewritten = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert "--allow-awaiting-deployment" not in forwarded
    assert rewritten["diagnostic"]["release_matches_expected"] is False
    assert rewritten["failure_class"] == "deployment_unresolved"
    assert rewritten["awaiting_deployment"] is True
    assert rewritten["deployment_resolution_required"] is True


def test_wrapper_keeps_release_mismatch_strict_without_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "telemetry.json"

    def fake_main(arguments: object) -> int:
        output.write_text(json.dumps(_snapshot()), encoding="utf-8")
        return resilient._base._EXIT_RELEASE_MISMATCH

    monkeypatch.setattr(resilient._base, "main", fake_main)

    code = resilient.main(
        [
            "--url",
            "https://example.invalid/telemetry.json",
            "--expected-release",
            "expected-main-sha",
            "--output",
            str(output),
        ]
    )

    assert code == resilient._base._EXIT_RELEASE_MISMATCH


def test_wrapper_keeps_unsafe_release_mismatch_strict_with_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "telemetry.json"
    unsafe = _snapshot()
    unsafe["paper_only"] = False

    def fake_main(arguments: object) -> int:
        output.write_text(json.dumps(unsafe), encoding="utf-8")
        return resilient._base._EXIT_RELEASE_MISMATCH

    monkeypatch.setattr(resilient._base, "main", fake_main)

    code = resilient.main(
        [
            "--url",
            "https://example.invalid/telemetry.json",
            "--expected-release",
            "expected-main-sha",
            "--output",
            str(output),
            "--allow-awaiting-deployment",
        ]
    )

    assert code == resilient._base._EXIT_RELEASE_MISMATCH
