from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement anchor, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "run_render_service_memory_safe.py",
    '_PROVIDER_VALIDATION_BACKGROUND_ENABLED = False\n_QUALIFIER_FAILURE_CONTEXT_EVENT = "continuous_evidence_plane_failure_context"\n',
    '_PROVIDER_VALIDATION_BACKGROUND_ENABLED = False\n_QUALIFIER_FAILURE_CONTEXT_EVENT = "continuous_evidence_plane_failure_context"\n_RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV = (\n    "CAPITAL_INTELLIGENCE_RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG"\n)\n',
)
replace_once(
    "run_render_service_memory_safe.py",
    "def _qualifier_metrics(\n",
    'def _release_prequalification_progress_watchdog_active() -> bool:\n    """Return true only after the exact parent subprocess watchdog is installed."""\n\n    proxy_type = type(subprocess)\n    return (\n        proxy_type.__module__ == "operations.release_prequalification_parent_watchdog"\n        and proxy_type.__name__ == "_SubprocessProxy"\n    )\n\n\ndef _release_prequalification_subprocess_env(\n    values: Mapping[str, str],\n) -> dict[str, str]:\n    resolved = dict(values)\n    if _release_prequalification_progress_watchdog_active():\n        resolved[_RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV] = "true"\n    return resolved\n\n\ndef _qualifier_metrics(\n',
)
replace_once(
    "run_render_service_memory_safe.py",
    '        completed: subprocess.CompletedProcess | None = None\n        start_error: OSError | None = None\n        try:\n            completed = subprocess.run(\n                evidence_command,\n                env=dict(diagnostic_values),\n',
    '        completed: subprocess.CompletedProcess | None = None\n        start_error: OSError | None = None\n        qualifier_env = _release_prequalification_subprocess_env(diagnostic_values)\n        try:\n            completed = subprocess.run(\n                evidence_command,\n                env=qualifier_env,\n',
)

replace_once(
    "run_bounded_render_worker.py",
    "from render_memory_lane import acquire_memory_lane\n\n\n@dataclass",
    'from render_memory_lane import acquire_memory_lane\n\n\n_RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV = (\n    "CAPITAL_INTELLIGENCE_RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG"\n)\n_TRUTHY = frozenset({"1", "true", "yes", "on"})\n\n\n@dataclass',
)
replace_once(
    "run_bounded_render_worker.py",
    "def _log(worker: str, event: str, **details: object) -> None:\n",
    'def _aggregate_timeout_enabled(spec: WorkerSpec, values: Mapping[str, str]) -> bool:\n    """Keep generic worker deadlines, except under the exact release progress watchdog."""\n\n    supervised = (\n        spec.name == "continuous-evidence-plane"\n        and str(values.get(_RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV) or "")\n        .strip()\n        .lower()\n        in _TRUTHY\n    )\n    return not supervised\n\n\ndef _log(worker: str, event: str, **details: object) -> None:\n',
)
replace_once(
    "run_bounded_render_worker.py",
    '    if timeout <= 0:\n        raise ValueError("timeout_seconds must be positive")\n    if lane_wait_seconds < 0:\n',
    '    if timeout <= 0:\n        raise ValueError("timeout_seconds must be positive")\n    aggregate_timeout_enabled = _aggregate_timeout_enabled(spec, resolved)\n    resource_wait_timeout = timeout if aggregate_timeout_enabled else None\n    if lane_wait_seconds < 0:\n',
)
replace_once(
    "run_bounded_render_worker.py",
    "            memory_accounting_source=accounting_source,\n            exclusive_heavy_memory_lane=True,\n",
    "            memory_accounting_source=accounting_source,\n            exclusive_heavy_memory_lane=True,\n            aggregate_timeout_enforced=aggregate_timeout_enabled,\n            aggregate_timeout_seconds=timeout if aggregate_timeout_enabled else None,\n",
)
replace_once(
    "run_bounded_render_worker.py",
    "                process,\n                timeout_seconds=timeout,\n",
    "                process,\n                timeout_seconds=resource_wait_timeout,\n",
)

replace_once(
    "operations/reclaimable_memory_guard.py",
    "    timeout_seconds: float,\n    memory_high_water_fraction: float,\n",
    "    timeout_seconds: float | None,\n    memory_high_water_fraction: float,\n",
)
replace_once(
    "operations/reclaimable_memory_guard.py",
    "    worker callers remain unchanged: ``(return_code, timed_out, memory_limited,\n    process_peak_kib, raw_container_peak_kib)``.\n",
    "    worker callers remain unchanged: ``(return_code, timed_out, memory_limited,\n    process_peak_kib, raw_container_peak_kib)``. ``timeout_seconds=None`` is reserved for\n    a child already supervised by the release prequalification durable-progress watchdog;\n    memory sampling and both existing memory boundaries remain active.\n",
)
replace_once(
    "operations/reclaimable_memory_guard.py",
    '    if timeout_seconds <= 0:\n        raise ValueError("timeout_seconds must be positive")\n',
    '    if timeout_seconds is not None and timeout_seconds <= 0:\n        raise ValueError("timeout_seconds must be positive")\n',
)

Path("tests/test_progress_aware_prequalification_timeout.py").write_text(
    '''from __future__ import annotations\n\nimport subprocess as std_subprocess\n\nimport run_bounded_render_worker as bounded\nimport run_render_service_memory_safe as memory_safe\nfrom operations import reclaimable_memory_guard as guard\n\n\ndef _spec(name: str) -> bounded.WorkerSpec:\n    return bounded.WorkerSpec(\n        name=name,\n        script="noop.py",\n        arguments=(),\n        interval_env="INTERVAL",\n        default_interval_seconds=1.0,\n        timeout_env="TIMEOUT",\n        default_timeout_seconds=3600.0,\n        default_initial_delay_seconds=0.0,\n    )\n\n\ndef test_prequalification_flag_requires_installed_parent_watchdog(monkeypatch):\n    values = {"SENTINEL": "kept"}\n    monkeypatch.setattr(memory_safe, "subprocess", std_subprocess)\n    ordinary = memory_safe._release_prequalification_subprocess_env(values)\n    assert memory_safe._RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV not in ordinary\n\n    proxy_type = type("_SubprocessProxy", (), {})\n    proxy_type.__module__ = "operations.release_prequalification_parent_watchdog"\n    monkeypatch.setattr(memory_safe, "subprocess", proxy_type())\n    supervised = memory_safe._release_prequalification_subprocess_env(values)\n    assert supervised[memory_safe._RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV] == "true"\n    assert supervised["SENTINEL"] == "kept"\n    assert memory_safe._RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV not in values\n\n\ndef test_only_supervised_continuous_evidence_disables_aggregate_timeout():\n    flag = bounded._RELEASE_PREQUALIFICATION_PROGRESS_WATCHDOG_ENV\n    assert bounded._aggregate_timeout_enabled(_spec("continuous-evidence-plane"), {}) is True\n    assert bounded._aggregate_timeout_enabled(\n        _spec("continuous-evidence-plane"), {flag: "true"}\n    ) is False\n    assert bounded._aggregate_timeout_enabled(\n        _spec("historical-backfill"), {flag: "true"}\n    ) is True\n\n\nclass _ImmediateProcess:\n    pid = None\n\n    def __init__(self) -> None:\n        self.wait_timeout = "unset"\n\n    def wait(self, timeout=None):\n        self.wait_timeout = timeout\n        return 0\n\n\ndef test_reclaimable_guard_keeps_memory_sampling_with_no_aggregate_timeout(monkeypatch):\n    snapshot = guard.MemorySnapshot(\n        raw_current_kib=None,\n        limit_kib=None,\n        working_set_kib=None,\n        inactive_file_kib=None,\n        anon_kib=None,\n        file_kib=None,\n        kernel_kib=None,\n        source="unavailable",\n    )\n    monkeypatch.setattr(guard, "memory_snapshot", lambda values: snapshot)\n    process = _ImmediateProcess()\n    result = guard.wait_with_reclaimable_resource_bounds(\n        process,\n        timeout_seconds=None,\n        memory_high_water_fraction=0.70,\n        values={},\n        memory_reserve_kib=0,\n        poll_seconds=0.01,\n    )\n    assert process.wait_timeout is None\n    assert result[:3] == (0, False, False)\n''',
    encoding="utf-8",
)
