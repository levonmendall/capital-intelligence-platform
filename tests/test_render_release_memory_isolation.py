from __future__ import annotations

import pytest

from run_render_service import ManagedProcess, _partition_startup_processes
from run_render_service_nonblocking import _diagnostic_completion_gate


def _managed(name: str) -> ManagedProcess:
    return ManagedProcess(name=name, command=("python-test", name))


def test_release_diagnostic_defers_duplicate_non_web_workers() -> None:
    specs = (
        _managed("api"),
        _managed("cio-paper-operator"),
        _managed("public-headline-collector"),
        _managed("historical-backfill"),
        _managed("encrypted-backup"),
        _managed("streamlit"),
        _managed("composite-readiness-watchdog"),
    )

    immediate, deferred = _partition_startup_processes(specs, defer_non_web=True)

    assert [spec.name for spec in immediate] == ["api", "streamlit"]
    assert [spec.name for spec in deferred] == [
        "cio-paper-operator",
        "public-headline-collector",
        "historical-backfill",
        "encrypted-backup",
        "composite-readiness-watchdog",
    ]


def test_normal_startup_keeps_all_children_immediate() -> None:
    specs = (_managed("api"), _managed("streamlit"), _managed("worker"))

    immediate, deferred = _partition_startup_processes(specs, defer_non_web=False)

    assert immediate == specs
    assert deferred == ()


def test_release_diagnostic_isolation_requires_both_public_children() -> None:
    with pytest.raises(ValueError, match="streamlit"):
        _partition_startup_processes((_managed("api"),), defer_non_web=True)


def test_diagnostic_completion_gate_opens_only_after_thread_finishes() -> None:
    class ThreadState:
        alive = True

        def is_alive(self) -> bool:
            return self.alive

    thread = ThreadState()
    gate = _diagnostic_completion_gate(thread)  # type: ignore[arg-type]

    assert gate is not None
    assert gate() is False
    thread.alive = False
    assert gate() is True
    assert _diagnostic_completion_gate(None) is None
