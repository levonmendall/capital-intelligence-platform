from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

import run_bounded_render_worker as bounded
from operations import release_prequalification_timeout_contract as contract


def _spec(name: str) -> bounded.WorkerSpec:
    return bounded.WorkerSpec(
        name=name,
        script="noop.py",
        arguments=(),
        interval_env="INTERVAL",
        default_interval_seconds=1.0,
        timeout_env="TIMEOUT",
        default_timeout_seconds=3600.0,
        default_initial_delay_seconds=0.0,
    )


def test_only_parent_supervised_continuous_evidence_loses_aggregate_clock():
    flag = bounded._RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV
    continuous = _spec("continuous-evidence-plane")
    historical = _spec("historical-backfill")

    assert bounded._aggregate_timeout_enabled(continuous, {}) is True
    assert bounded._resource_wait_timeout(continuous, {}, 3600.0) == 3600.0
    assert bounded._aggregate_timeout_enabled(continuous, {flag: "false"}) is True
    assert bounded._resource_wait_timeout(continuous, {flag: "false"}, 3600.0) == 3600.0

    assert bounded._aggregate_timeout_enabled(continuous, {flag: "true"}) is False
    assert math.isinf(bounded._resource_wait_timeout(continuous, {flag: "true"}, 3600.0))

    assert bounded._aggregate_timeout_enabled(historical, {flag: "true"}) is True
    assert bounded._resource_wait_timeout(historical, {flag: "true"}, 3600.0) == 3600.0


def _parent_proxy_type():
    class ParentProxyBase:
        def __init__(self) -> None:
            self.calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

        def run(self, command, *args, **kwargs):
            self.calls.append((command, args, dict(kwargs)))
            return "completed"

    proxy_type = type(contract._PARENT_PROXY_NAME, (ParentProxyBase,), {})
    proxy_type.__module__ = contract._PARENT_PROXY_MODULE
    return proxy_type


def test_timeout_marker_is_added_only_through_exact_parent_watchdog_proxy():
    parent = _parent_proxy_type()()
    memory_safe = SimpleNamespace(subprocess=parent)
    contract.install_release_prequalification_timeout_contract(memory_safe)

    original_env = {"SENTINEL": "kept"}
    result = memory_safe.subprocess.run(
        ("python", "run_bounded_continuous_evidence_plane.py"),
        env=original_env,
        check=False,
    )

    assert result == "completed"
    assert original_env == {"SENTINEL": "kept"}
    assert len(parent.calls) == 1
    delegated_env = parent.calls[0][2]["env"]
    assert delegated_env["SENTINEL"] == "kept"
    assert delegated_env[contract._SUPERVISION_ENV] == "true"

    memory_safe.subprocess.run(("python", "other_worker.py"), env=original_env)
    ordinary_env = parent.calls[1][2]["env"]
    assert contract._SUPERVISION_ENV not in ordinary_env


def test_timeout_contract_rejects_install_without_parent_watchdog():
    with pytest.raises(RuntimeError, match="requires the release prequalification parent watchdog"):
        contract.install_release_prequalification_timeout_contract(
            SimpleNamespace(subprocess=object())
        )
