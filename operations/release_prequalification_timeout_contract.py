"""Mark only the release-prequalification evidence child as progress-supervised.

The release bootstrap already installs a durable-progress subprocess watchdog around the
one-shot continuous evidence command. That parent watchdog owns finite stage/lane/DAG stall
termination. This module adds a credential-safe environment marker only while that exact
proxy is wrapping the evidence command, allowing the inner bounded worker to avoid a
competing aggregate wall-clock deadline while retaining its unchanged memory guard.

The same startup seam also installs the granular futures-reference progress projection so
the parent sees the venue/root checkpoints already persisted by the reference coordinator.
It also binds retry observation to the persisted prequalification generation start so a
wrapper retry cannot hide valid same-generation stage progress. Neither adapter extends any
provider or stall timeout.

This is operational coordination only. It has no evidence, candidate, CIO, construction,
sizing, execution, or real-money authority.
"""

from __future__ import annotations

import os
from types import ModuleType

from operations.granular_futures_parent_watchdog_progress import (
    install_granular_futures_parent_watchdog_progress,
)
from operations.release_prequalification_retry_progress_boundary import (
    install_release_prequalification_retry_progress_boundary,
)


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


def _install_parent_progress_adapters() -> None:
    install_release_prequalification_retry_progress_boundary()
    install_granular_futures_parent_watchdog_progress()


def install_release_prequalification_timeout_contract(memory_safe_module: ModuleType) -> None:
    """Install only after the exact durable-progress parent proxy is active."""

    current = getattr(memory_safe_module, "subprocess", None)
    if isinstance(current, _ProgressSupervisedSubprocessProxy):
        _install_parent_progress_adapters()
        return
    current_type = type(current)
    if (
        current_type.__module__ != _PARENT_PROXY_MODULE
        or current_type.__name__ != _PARENT_PROXY_NAME
    ):
        raise RuntimeError(
            "progress-aware timeout contract requires the release prequalification parent watchdog"
        )
    _install_parent_progress_adapters()
    memory_safe_module.subprocess = _ProgressSupervisedSubprocessProxy(current)


__all__ = [
    "install_release_prequalification_timeout_contract",
]
