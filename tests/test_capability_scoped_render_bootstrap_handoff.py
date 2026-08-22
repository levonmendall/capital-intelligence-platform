from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from operations.manual_cio_diagnostic import request_manual_cio_diagnostic
from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)
from operations import capability_scoped_render_bootstrap as subject


class _RenderBootstrap:
    def __init__(self) -> None:
        self.audit_publications = 0
        self.events: list[tuple[str, dict[str, object]]] = []

    def _publish_release_diagnostic_audit(self, _values) -> int:
        self.audit_publications += 1
        return 0

    def _log(self, event: str, **details: object) -> None:
        self.events.append((event, details))


class _MemorySafe:
    def __init__(self) -> None:
        self.render_bootstrap = _RenderBootstrap()

    @staticmethod
    def _positive_int(values, name: str, default: int) -> int:
        raw = str(values.get(name) or "").strip()
        return int(raw) if raw else default

    @staticmethod
    def _nonnegative_seconds(values, name: str, default: float) -> float:
        raw = str(values.get(name) or "").strip()
        return float(raw) if raw else default


def _values(tmp_path: Path, release: str = "release-current") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": release,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
        "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_ATTEMPTS": "1",
        "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_SUBPROCESS_TIMEOUT_SECONDS": "1",
    }


def _prime_broad_generation(values: dict[str, str]) -> None:
    write_release_evidence_prequalification(
        values,
        state="completed",
        stage="evidence_generation_ready",
        detail="broad all-market generation ready",
        generation_id="generation-current",
        metrics={"complete_all_market_coverage_required": 1},
    )


def test_capability_prequalification_timeout_fails_closed_and_does_not_stay_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values = _values(tmp_path)
    _prime_broad_generation(values)
    memory_safe = _MemorySafe()

    def timeout_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="capability", timeout=1)

    monkeypatch.setattr(subject.subprocess, "run", timeout_run)

    assert subject.prequalify_capability_operating_evidence(memory_safe, values) is False

    status = load_release_evidence_prequalification(values)
    assert status is not None
    assert status["state"] == "failed"
    assert status["stage"] == "evidence_prequalification_failed"
    assert "capability_operating_evidence_timeout" in str(status["detail"])
    assert status["generation_id"] == "generation-current"
    assert status["metrics"]["capability_operating_evidence_timeout"] == 1
    assert memory_safe.audit_publications >= 2


def test_capability_prequalification_success_restores_ready_only_after_fresh_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values = _values(tmp_path)
    _prime_broad_generation(values)
    memory_safe = _MemorySafe()

    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=("capability",),
            returncode=0,
            stdout="",
        ),
    )
    evidence = SimpleNamespace(
        snapshot_id="capability-snapshot-current",
        universe=SimpleNamespace(instruments=(SimpleNamespace(symbol="SPY"),)),
        holding_only_symbols=(),
    )
    monkeypatch.setattr(
        subject,
        "load_capability_operating_evidence",
        lambda **_kwargs: evidence,
    )

    assert subject.prequalify_capability_operating_evidence(memory_safe, values) is True

    status = load_release_evidence_prequalification(values)
    assert status is not None
    assert status["state"] == "completed"
    assert status["stage"] == "evidence_generation_ready"
    assert status["generation_id"] == "generation-current"
    assert values["CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"] == (
        "capability-snapshot-current"
    )


def test_current_release_handoff_rejects_stale_prior_release_request(tmp_path: Path) -> None:
    prior = _values(tmp_path, release="release-prior")
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-prior",
        values=prior,
    )
    assert created is True
    assert request.state == "pending"

    current = _values(tmp_path, release="release-current")
    assert subject._verify_current_release_handoff(current) is False


def test_current_release_handoff_accepts_exact_release_pending_request(tmp_path: Path) -> None:
    values = _values(tmp_path)
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-current",
        values=values,
    )
    assert created is True
    assert request.state == "pending"

    assert subject._verify_current_release_handoff(values) is True
