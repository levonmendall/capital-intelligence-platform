"""Install the exact-stage prequalification audit publisher in the Render bootstrap."""

from __future__ import annotations

import sys


def install(render_bootstrap) -> None:
    """Route release audit publications through the stage-isolated projection wrapper."""

    def command(*, python_executable: str | None = None) -> tuple[str, ...]:
        return (
            python_executable or sys.executable,
            "publish_cio_diagnostic_audit_stage_isolated.py",
        )

    render_bootstrap._release_diagnostic_audit_command = command


__all__ = ["install"]
