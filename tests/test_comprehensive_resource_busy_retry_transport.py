from __future__ import annotations

from operations import comprehensive_discovery_runtime_contract as contract
from operations import spawn_safe_authoritative_acquisition as spawn_safe


def test_resource_busy_failure_gets_bounded_retry_hint(monkeypatch) -> None:
    def load_failure(*args, **kwargs):
        del args, kwargs
        return RuntimeError(
            "comprehensive discovery spool unavailable (resource_busy) for provider alpaca"
        )

    monkeypatch.setattr(spawn_safe, "_load_lane_failure", load_failure)
    contract._install_resource_busy_retry_transport()

    error = spawn_safe._load_lane_failure()

    assert error.retry_after_seconds == 3.0


def test_existing_retry_hint_is_preserved(monkeypatch) -> None:
    def load_failure(*args, **kwargs):
        del args, kwargs
        error = RuntimeError("resource_busy")
        error.retry_after_seconds = 17.0
        return error

    monkeypatch.setattr(spawn_safe, "_load_lane_failure", load_failure)
    contract._install_resource_busy_retry_transport()

    error = spawn_safe._load_lane_failure()

    assert error.retry_after_seconds == 17.0


def test_non_resource_busy_failure_remains_terminal(monkeypatch) -> None:
    def load_failure(*args, **kwargs):
        del args, kwargs
        return RuntimeError("provider returned malformed evidence")

    monkeypatch.setattr(spawn_safe, "_load_lane_failure", load_failure)
    contract._install_resource_busy_retry_transport()

    error = spawn_safe._load_lane_failure()

    assert not hasattr(error, "retry_after_seconds")


def test_resource_busy_cause_is_retryable(monkeypatch) -> None:
    def load_failure(*args, **kwargs):
        del args, kwargs
        error = RuntimeError("comprehensive lane failed")
        error.__cause__ = RuntimeError("resource_busy")
        return error

    monkeypatch.setattr(spawn_safe, "_load_lane_failure", load_failure)
    contract._install_resource_busy_retry_transport()

    error = spawn_safe._load_lane_failure()

    assert error.retry_after_seconds == 3.0
