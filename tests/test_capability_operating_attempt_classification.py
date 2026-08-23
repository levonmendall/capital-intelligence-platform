from __future__ import annotations

import json
import subprocess
from pathlib import Path

from operations import capability_scoped_render_bootstrap as subject
from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)


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


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-current",
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


def _safe_event(event: str, **extra: object) -> str:
    return json.dumps(
        {
            "event": event,
            "paper_only": True,
            "real_money_authorized": False,
            **extra,
        },
        sort_keys=True,
    )


def test_memory_lane_busy_is_durable_resource_busy_failure(
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
            returncode=126,
            stdout=_safe_event("heavy_memory_lane_busy"),
        ),
    )

    assert subject.prequalify_capability_operating_evidence(memory_safe, values) is False

    status = load_release_evidence_prequalification(values)
    assert status is not None
    assert status["state"] == "failed"
    context = status["failure_context"]
    assert isinstance(context, dict)
    assert context["capability"] == "capability_operating_evidence"
    assert context["failure_stage"] == "capability_operating_gate"
    assert context["reason"] == "resource_busy"
    assert context["error_type"] == "CapabilityOperatingEvidenceMemoryLaneBusy"
    assert status["metrics"]["capability_operating_evidence_return_code"] == 126
    assert status["metrics"]["capability_operating_evidence_resource_busy"] == 1
    assert status["metrics"]["capability_operating_evidence_timeout"] == 0


def test_memory_limited_attempt_classifies_resource_exhaustion() -> None:
    reason, error_type, detail_token, event = subject._classify_capability_attempt_failure(
        return_code=125,
        output=_safe_event("isolated_worker_pass_memory_limited"),
        timed_out=False,
    )

    assert reason == "resource_exhausted"
    assert error_type == "CapabilityOperatingEvidenceMemoryLimited"
    assert detail_token == "capability_operating_evidence_memory_limited"
    assert event == "isolated_worker_pass_memory_limited"


def test_safe_child_error_type_survives_without_raw_child_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values = _values(tmp_path)
    _prime_broad_generation(values)
    memory_safe = _MemorySafe()
    stdout = _safe_event(
        "capability_operating_evidence_failed",
        credential_safe=True,
        error_type="CapabilityOperatingEvidenceError",
    )
    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=("capability",),
            returncode=2,
            stdout=stdout,
        ),
    )

    assert subject.prequalify_capability_operating_evidence(memory_safe, values) is False

    status = load_release_evidence_prequalification(values)
    assert status is not None
    context = status["failure_context"]
    assert isinstance(context, dict)
    assert context["capability"] == "capability_operating_evidence"
    assert context["reason"] == "internal_error"
    assert context["error_type"] == "CapabilityOperatingEvidenceError"
    assert context["failure_stage"] == "capability_operating_gate"
    assert "capability_operating_evidence_unavailable" in str(status["detail"])


def test_untrusted_child_output_is_not_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values = _values(tmp_path)
    _prime_broad_generation(values)
    memory_safe = _MemorySafe()
    raw_secret = "provider_url=https://example.invalid/?api_key=do-not-persist"
    unsafe = json.dumps(
        {
            "event": "capability_operating_evidence_failed",
            "credential_safe": False,
            "error_type": "UnsafeError",
            "paper_only": True,
            "real_money_authorized": False,
            "detail": raw_secret,
        }
    )
    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=("capability",),
            returncode=2,
            stdout=unsafe,
        ),
    )

    assert subject.prequalify_capability_operating_evidence(memory_safe, values) is False

    status = load_release_evidence_prequalification(values)
    assert status is not None
    serialized = json.dumps(status, sort_keys=True)
    assert "do-not-persist" not in serialized
    assert "example.invalid" not in serialized
    context = status["failure_context"]
    assert isinstance(context, dict)
    assert context["error_type"] == "CapabilityOperatingEvidenceUnavailable"


def test_outer_timeout_remains_explicit_deadline_failure() -> None:
    reason, error_type, detail_token, event = subject._classify_capability_attempt_failure(
        return_code=124,
        output="",
        timed_out=True,
    )

    assert reason == "deadline_exceeded"
    assert error_type == "CapabilityOperatingEvidenceTimeout"
    assert detail_token == "capability_operating_evidence_timeout"
    assert event == "outer_subprocess_timeout"
