from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import run_manual_cio_diagnostic as diagnostic
from operations.certification_state_machine import CertificationState


AS_OF = "2026-08-30T19:06:36.031815+00:00"


def test_ranked_current_no_transaction_stays_non_terminal_for_release_diagnostic() -> None:
    briefing = {
        "identifier": f"daily-cio:{AS_OF}",
        "decision_identifier": "decision:btc-hold",
        "candidate_identifier": "candidate:btc",
        "cio_decision_count": 1,
        "as_of": AS_OF,
        "status": "current",
        "construction_status": None,
        "portfolio_decision": (
            "CIO decision: hold. No executable portfolio change is proposed."
        ),
    }

    assert diagnostic._governed_no_action(briefing) is False


def test_explicit_empty_queue_no_action_remains_terminal() -> None:
    briefing = {
        "identifier": f"daily-cio:{AS_OF}",
        "as_of": AS_OF,
        "status": "no_superior_opportunity",
        "portfolio_decision": "No qualified opportunity exceeded the cash hurdle.",
    }

    assert diagnostic._governed_no_action(briefing) is True


class _CompletedWorker:
    def run_triggered(self, *args: object, **kwargs: object) -> object:
        return SimpleNamespace(status="completed")


def _guard_type() -> type:
    return diagnostic._load_worker_dependency.__globals__["_ExactReleaseCertificationGuard"]


def test_exact_release_completed_worker_fails_closed_before_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import operations.certification_runtime_state as runtime_state

    monkeypatch.setattr(runtime_state, "certification_runtime_enabled", lambda: True)
    monkeypatch.setattr(
        runtime_state,
        "resolve_certification_for_cutoff",
        lambda cutoff: SimpleNamespace(current_state=CertificationState.CIO_COMPLETE),
    )
    guard = _guard_type()(_CompletedWorker())
    decision_as_of = datetime.fromisoformat(AS_OF)

    with pytest.raises(
        RuntimeError,
        match="current=cio_complete, required=construction_complete",
    ):
        guard.run_triggered(
            "manual-cio",
            now=datetime.now(timezone.utc),
            decision_as_of=decision_as_of,
        )


def test_exact_release_completed_worker_advances_only_after_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import operations.certification_runtime_state as runtime_state

    monkeypatch.setattr(runtime_state, "certification_runtime_enabled", lambda: True)
    monkeypatch.setattr(
        runtime_state,
        "resolve_certification_for_cutoff",
        lambda cutoff: SimpleNamespace(
            current_state=CertificationState.CONSTRUCTION_COMPLETE
        ),
    )
    guard = _guard_type()(_CompletedWorker())

    result = guard.run_triggered(
        "manual-cio",
        now=datetime.now(timezone.utc),
        decision_as_of=datetime.fromisoformat(AS_OF),
    )

    assert result.status == "completed"


def test_non_certification_runtime_keeps_existing_worker_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import operations.certification_runtime_state as runtime_state

    monkeypatch.setattr(runtime_state, "certification_runtime_enabled", lambda: False)
    guard = _guard_type()(_CompletedWorker())

    result = guard.run_triggered(
        "manual-cio",
        now=datetime.now(timezone.utc),
        decision_as_of=datetime.fromisoformat(AS_OF),
    )

    assert result.status == "completed"
