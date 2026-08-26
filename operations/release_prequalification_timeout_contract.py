"""Mark only the release-prequalification evidence child as progress-supervised.

The release bootstrap already installs a durable-progress subprocess watchdog around the
one-shot continuous evidence command. That parent watchdog owns finite stage/lane/DAG stall
termination. This module adds a credential-safe environment marker only while that exact
proxy is wrapping the evidence command, allowing the inner bounded worker to avoid a
competing aggregate wall-clock deadline while retaining its unchanged memory guard.

This is operational coordination only. It has no evidence, candidate, CIO, construction,
sizing, execution, or real-money authority.
"""

from __future__ import annotations

import os
from types import ModuleType


_EVIDENCE_SCRIPT = "run_bounded_continuous_evidence_plane.py"
_SUPERVISION_ENV = "CAPITAL_INTELLIGENCE_RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG"
_PARENT_PROXY_MODULE = "operations.release_prequalification_parent_watchdog"
_PARENT_PROXY_NAME = "_SubprocessProxy"


def _is_evidence_command(command: object) -> bool:
    if isinstance(command, (str, bytes)):
        return _EVIDENCE_SCRIPT in str(command)
    try:
        return any(str(item).endswith(_EVIDENCE_SCRIPT) for item in command)  # type: ignore[union-attr]
    except TypeError:
        return False


class _ProgressSupervisedSubprocessProxy:
    """Delegate to the installed parent watchdog while marking only its evidence child."""

    def __init__(self, parent_proxy: object) -> None:
        self._parent_proxy = parent_proxy

    def __getattr__(self, name: str):
        return getattr(self._parent_proxy, name)

    def run(self, command, *args, **kwargs):
        if args or not _is_evidence_command(command):
            return self._parent_proxy.run(command, *args, **kwargs)
        delegated = dict(kwargs)
        child_env = dict(delegated.get("env") or os.environ)
        child_env[_SUPERVISION_ENV] = "true"
        delegated["env"] = child_env
        return self._parent_proxy.run(command, **delegated)


def install_release_prequalification_timeout_contract(memory_safe_module: ModuleType) -> None:
    """Install only after the exact durable-progress parent proxy is active."""

    current = getattr(memory_safe_module, "subprocess", None)
    if isinstance(current, _ProgressSupervisedSubprocessProxy):
        return
    current_type = type(current)
    if (
        current_type.__module__ != _PARENT_PROXY_MODULE
        or current_type.__name__ != _PARENT_PROXY_NAME
    ):
        raise RuntimeError(
            "progress-aware timeout contract requires the release prequalification parent watchdog"
        )
    memory_safe_module.subprocess = _ProgressSupervisedSubprocessProxy(current)


__all__ = [
    "install_release_prequalification_timeout_contract",
]
