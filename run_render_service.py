"""Run the complete Capital Intelligence operating system as one Render service.

Render persistent disks attach to a single service instance. This supervisor therefore
runs the authenticated Streamlit console, read-only API, autonomous CIO/paper operator,
redundant headline collector, historical backfill loop, and encrypted backup loop as
child processes that share one durable SQLite and research-data state root.

The supervisor is intentionally fail-closed:

* initialization must succeed before any child starts;
* the public web, API, and CIO operator are critical processes;
* loss of a critical process terminates the service so Render restarts it;
* headline, historical, backup, and readiness-monitoring loops are restarted with
  bounded delay without taking the trading console down during a transient or
  persistently blocked operational condition;
* an explicitly supplied release-diagnostic barrier starts only API and Streamlit until
  the bounded all-market diagnostic finishes, avoiding duplicate heavyweight workers;
* SIGTERM is forwarded to every child for an orderly deployment shutdown; and
* no live-money authority is introduced.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Mapping, MutableMapping

from cryptography.fernet import Fernet
from operations.composite_readiness import component_heartbeat_path
from operations.heartbeat import WorkerHeartbeatStore


_RELEASE_DIAGNOSTIC_STARTUP_CHILDREN = frozenset({"api", "streamlit"})


@dataclass(frozen=True, slots=True)
class ManagedProcess:
    name: str
    command: tuple[str, ...]
    critical: bool = True
    restart_delay_seconds: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("managed process name cannot be empty")
        if not self.command or any(not str(part).strip() for part in self.command):
            raise ValueError("managed process command cannot be empty")
        if self.restart_delay_seconds < 0:
            raise ValueError("restart_delay_seconds cannot be negative")


def _write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (value.strip() + "\n").encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    temporary.replace(path)
    path.chmod(0o600)


def _persistent_secret(path: Path, generator) -> str:
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError(f"persistent runtime secret is empty: {path}")
        return value
    value = str(generator()).strip()
    if not value:
        raise RuntimeError(f"runtime secret generator returned an empty value: {path}")
    _write_private_text(path, value)
    return value


def prepare_render_environment(
    environ: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    """Apply secure Render defaults without overwriting explicitly supplied values."""

    values = os.environ if environ is None else environ
    state_root = Path(
        values.get(
            "CAPITAL_INTELLIGENCE_DATA_DIR",
            "/app/database" if values.get("RENDER") == "true" else "database",
        )
    ).expanduser()
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "backups").mkdir(parents=True, exist_ok=True)
    (state_root / "cio_reports").mkdir(parents=True, exist_ok=True)
    (state_root / "historical_replay").mkdir(parents=True, exist_ok=True)

    values.setdefault("CAPITAL_INTELLIGENCE_DATA_DIR", str(state_root))
    values.setdefault(
        "CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY",
        str(state_root / "backups"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_CIO_REPORT_DIRECTORY",
        str(state_root / "cio_reports"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR",
        str(state_root / "historical_replay"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_HISTORICAL_CONFIG",
        "config/historical_replay_free_sources.json",
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_HISTORICAL_INTERVAL_SECONDS",
        "86400",
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_HISTORICAL_MAX_RECORDS_PER_SOURCE",
        "100000",
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT",
        str(state_root / "public-live-information-report.json"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS",
        str(state_root / "public-live-information-records.json"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_STATE",
        str(state_root / "public-live-information-runtime-state.json"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_LOCK",
        str(state_root / "public-live-information-runtime.lock"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_REPORT",
        str(state_root / "public-headline-collection-report.json"),
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_STATE",
        str(state_root / "public-headline-collection-state.json"),
    )

    values.setdefault("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")
    values.setdefault("CAPITAL_INTELLIGENCE_JSON_LOGS", "true")
    values.setdefault("CAPITAL_INTELLIGENCE_SERVICE_NAME", "capital-intelligence-render")
    values.setdefault("CAPITAL_INTELLIGENCE_ENFORCE_HTTPS", "true")
    values.setdefault("CAPITAL_INTELLIGENCE_REQUIRE_ENCRYPTED_BACKUPS", "true")
    values.setdefault("CAPITAL_INTELLIGENCE_REQUIRE_OPERATIONAL_SLOS", "true")
    values.setdefault("CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED", "true")
    values.setdefault("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE", "automatic")
    values.setdefault("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED", "true")
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS",
        "3600",
    )
    values.setdefault(
        "CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_INTERVAL_SECONDS",
        "300",
    )
    values.setdefault("CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE", "America/New_York")
    values.setdefault("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "7")
    values.setdefault("CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS", "60")
    values.setdefault("CAPITAL_INTELLIGENCE_BACKUP_INTERVAL_HOURS", "24")
    values.setdefault("CAPITAL_INTELLIGENCE_BACKUP_RETENTION_DAYS", "30")

    release = (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    )
    values["CAPITAL_INTELLIGENCE_RELEASE"] = release

    external_hostname = values.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    configured_hosts = [
        item.strip()
        for item in values.get("CAPITAL_INTELLIGENCE_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    ]
    for host in (external_hostname, "localhost", "127.0.0.1"):
        if host and host not in configured_hosts:
            configured_hosts.append(host)
    values["CAPITAL_INTELLIGENCE_ALLOWED_HOSTS"] = ",".join(configured_hosts)

    external_url = values.get("RENDER_EXTERNAL_URL", "").strip()
    if external_url and not values.get("CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS", "").strip():
        values["CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS"] = external_url

    if not values.get("CAPITAL_INTELLIGENCE_METRICS_TOKEN", "").strip():
        values["CAPITAL_INTELLIGENCE_METRICS_TOKEN"] = _persistent_secret(
            state_root / ".metrics-token",
            lambda: secrets.token_urlsafe(32),
        )
    if not values.get("CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY", "").strip():
        values["CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY"] = _persistent_secret(
            state_root / ".backup-encryption-key",
            lambda: Fernet.generate_key().decode("ascii"),
        )

    return values


def managed_processes(
    *,
    port: int,
    python_executable: str | None = None,
) -> tuple[ManagedProcess, ...]:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    python = python_executable or sys.executable
    return (
        ManagedProcess(
            name="api",
            command=(
                python,
                "-m",
                "uvicorn",
                "api.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--workers",
                "1",
                "--proxy-headers",
            ),
        ),
        ManagedProcess(
            name="cio-paper-operator",
            command=(python, "run_autonomous_paper_operator.py", "--loop"),
        ),
        ManagedProcess(
            name="public-headline-collector",
            command=(python, "run_public_headline_collector.py", "--loop"),
            critical=False,
            restart_delay_seconds=60,
        ),
        ManagedProcess(
            name="historical-backfill",
            command=(python, "run_historical_backfill.py", "--loop"),
            critical=False,
            restart_delay_seconds=300,
        ),
        ManagedProcess(
            name="encrypted-backup",
            command=(python, "run_backup.py", "--loop"),
            critical=False,
            restart_delay_seconds=300,
        ),
        ManagedProcess(
            name="streamlit",
            command=(
                python,
                "-m",
                "streamlit",
                "run",
                "render_app.py",
                "--server.address=0.0.0.0",
                f"--server.port={port}",
                "--server.headless=true",
                "--server.fileWatcherType=none",
                "--browser.gatherUsageStats=false",
            ),
        ),
        ManagedProcess(
            name="composite-readiness-watchdog",
            command=(python, "run_composite_readiness_watchdog.py"),
            critical=False,
            restart_delay_seconds=300,
        ),
    )


def _partition_startup_processes(
    specs: Sequence[ManagedProcess],
    *,
    defer_non_web: bool,
) -> tuple[tuple[ManagedProcess, ...], tuple[ManagedProcess, ...]]:
    """Return immediate and deferred process groups for a release diagnostic.

    A release diagnostic needs the API and Streamlit heartbeats, but starting the CIO
    operator, collectors, backfill, backup, and readiness watchdog at the same time adds
    avoidable Python/import working sets to the same 2 GB Render instance. Deferring only
    those non-web children preserves public health and diagnostic observability while
    preventing a duplicate heavyweight operating stack from competing for memory.
    """

    resolved = tuple(specs)
    if not defer_non_web:
        return resolved, ()

    names = {spec.name for spec in resolved}
    missing = _RELEASE_DIAGNOSTIC_STARTUP_CHILDREN.difference(names)
    if missing:
        raise ValueError(
            "release diagnostic startup requires managed children: "
            + ", ".join(sorted(missing))
        )
    immediate = tuple(
        spec for spec in resolved if spec.name in _RELEASE_DIAGNOSTIC_STARTUP_CHILDREN
    )
    deferred = tuple(
        spec for spec in resolved if spec.name not in _RELEASE_DIAGNOSTIC_STARTUP_CHILDREN
    )
    return immediate, deferred


def _log(event: str, **details: object) -> None:
    payload = {
        "event": event,
        "service": "capital-intelligence-render-supervisor",
        "timestamp": time.time(),
        "real_money_authorized": False,
        **details,
    }
    print(json.dumps(payload, sort_keys=True), flush=True)


def _start(spec: ManagedProcess, *, environment: Mapping[str, str]) -> subprocess.Popen:
    _log("child_starting", child=spec.name, command=list(spec.command))
    return subprocess.Popen(spec.command, env=dict(environment))


def _terminate_all(children: Mapping[str, subprocess.Popen]) -> None:
    for process in children.values():
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 20
    for process in children.values():
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
    for process in children.values():
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def run_supervisor(
    *,
    environment: MutableMapping[str, str] | None = None,
    poll_seconds: float = 1.0,
    deferred_start_ready: Callable[[], bool] | None = None,
) -> int:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    values = prepare_render_environment(environment)
    port = int(values.get("PORT", "10000"))

    _log(
        "initializing",
        release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        state_root=values.get("CAPITAL_INTELLIGENCE_DATA_DIR"),
        public_port=port,
    )
    subprocess.run(
        (sys.executable, "initialize.py"),
        env=dict(values),
        check=True,
    )

    specs = managed_processes(port=port)
    immediate_specs, deferred_specs = _partition_startup_processes(
        specs,
        defer_non_web=deferred_start_ready is not None,
    )
    active_specs = list(immediate_specs)
    if deferred_specs:
        _log(
            "release_diagnostic_memory_isolation_armed",
            immediate_children=[spec.name for spec in immediate_specs],
            deferred_children=[spec.name for spec in deferred_specs],
            public_service_available=True,
            paper_only=True,
        )

    state_root = Path(values["CAPITAL_INTELLIGENCE_DATA_DIR"])
    liveness_heartbeats = {
        name: WorkerHeartbeatStore(component_heartbeat_path(state_root, name))
        for name in ("api", "streamlit")
    }
    children: dict[str, subprocess.Popen] = {}
    restart_after: dict[str, float] = {}
    stopping = False

    def start_spec(spec: ManagedProcess) -> None:
        children[spec.name] = _start(spec, environment=values)
        if spec.name in liveness_heartbeats:
            liveness_heartbeats[spec.name].write(
                "starting",
                detail=f"{spec.name} child process started",
            )

    def request_stop(signum: int, frame: FrameType | None) -> None:
        del frame
        nonlocal stopping
        stopping = True
        _log("shutdown_requested", signal=signum)

    previous_handlers = {
        signal.SIGTERM: signal.signal(signal.SIGTERM, request_stop),
        signal.SIGINT: signal.signal(signal.SIGINT, request_stop),
    }
    exit_code = 0
    try:
        for spec in immediate_specs:
            start_spec(spec)

        while not stopping:
            if deferred_specs and deferred_start_ready is not None:
                if deferred_start_ready():
                    for spec in deferred_specs:
                        start_spec(spec)
                        active_specs.append(spec)
                    _log(
                        "release_diagnostic_memory_isolation_released",
                        started_children=[spec.name for spec in deferred_specs],
                        public_service_available=True,
                        paper_only=True,
                    )
                    deferred_specs = ()

            now = time.monotonic()
            for spec in tuple(active_specs):
                process = children.get(spec.name)
                if process is None:
                    due = restart_after.get(spec.name, 0.0)
                    if now >= due:
                        start_spec(spec)
                        restart_after.pop(spec.name, None)
                    continue
                return_code = process.poll()
                if return_code is None:
                    if spec.name in liveness_heartbeats:
                        liveness_heartbeats[spec.name].write(
                            "healthy",
                            detail=f"{spec.name} child process is running",
                        )
                    continue
                _log(
                    "child_exited",
                    child=spec.name,
                    return_code=return_code,
                    critical=spec.critical,
                )
                children.pop(spec.name, None)
                if spec.name in liveness_heartbeats:
                    liveness_heartbeats[spec.name].write(
                        "failed",
                        detail=f"{spec.name} child exited with code {return_code}",
                    )
                if spec.critical:
                    exit_code = return_code if return_code else 1
                    stopping = True
                    break
                restart_after[spec.name] = now + spec.restart_delay_seconds
            if not stopping:
                time.sleep(poll_seconds)
    finally:
        _terminate_all(children)
        for handled_signal, previous in previous_handlers.items():
            signal.signal(handled_signal, previous)
        _log("supervisor_stopped", exit_code=exit_code)
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError("run_render_service.py does not accept command-line arguments")
    try:
        return run_supervisor()
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, RuntimeError) as error:
        _log("supervisor_failed", error=str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
