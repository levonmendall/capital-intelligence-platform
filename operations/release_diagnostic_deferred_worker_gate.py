"""Keep non-serving heavyweight workers out of the release-certification window.

The memory-safe Render bootstrap starts release evidence prequalification and the exact-release
CIO diagnostic in one background thread, then starts the normal process supervisor. The
supervisor already supports a diagnostic barrier that starts only API and Streamlit until a
supplied completion predicate becomes true. This adapter reconnects those two existing
coordination seams so background evidence, CIO-operator, backup, backfill, provider-validation,
and readiness workers cannot overlap the governed release diagnostic.

This is startup scheduling only. It does not alter memory ceilings, evidence freshness or
coverage, market scope, strategy, specialist/CIO authority, portfolio construction,
paper-execution controls, or real-money authority.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from types import ModuleType
from typing import Any


_INSTALLED_ATTR = "_release_diagnostic_deferred_worker_gate_installed"


def install(memory_safe: ModuleType) -> None:
    """Defer non-web managed children while release certification is active."""

    if getattr(memory_safe, _INSTALLED_ATTR, False):
        return

    original_start = memory_safe._start_release_diagnostic_after_prequalification
    supervisor = memory_safe.render_supervisor
    original_run_supervisor = supervisor.run_supervisor
    active: dict[str, Any] = {"diagnostic_thread": None}

    def start_release_diagnostic_after_prequalification(
        values: MutableMapping[str, str],
    ):
        thread = original_start(values)
        active["diagnostic_thread"] = thread
        return thread

    def run_supervisor(
        *,
        environment: MutableMapping[str, str] | None = None,
        poll_seconds: float = 1.0,
        deferred_start_ready: Callable[[], bool] | None = None,
    ) -> int:
        gate = deferred_start_ready
        thread = active.get("diagnostic_thread")
        if gate is None and thread is not None:
            gate = lambda thread=thread: not thread.is_alive()
        return original_run_supervisor(
            environment=environment,
            poll_seconds=poll_seconds,
            deferred_start_ready=gate,
        )

    memory_safe._start_release_diagnostic_after_prequalification = (
        start_release_diagnostic_after_prequalification
    )
    supervisor.run_supervisor = run_supervisor
    setattr(memory_safe, _INSTALLED_ATTR, True)


__all__ = ["install"]
