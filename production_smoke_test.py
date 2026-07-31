"""Administrator-triggered verification for the persistent Render operating host.

The verifier is read-only except for three explicit artifacts under the configured
persistent data root:

* a pre-restart snapshot;
* the latest sanitized verification result; and
* an encrypted backup when the administrator explicitly requests one.

No credential value is read into a returned payload, and no trading authority is
created, changed, or exercised.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


SNAPSHOT_SCHEMA = "production-runtime-smoke-snapshot.v1"
RESULT_SCHEMA = "production-runtime-smoke-result.v1"
SNAPSHOT_FILENAME = "production-runtime-smoke-before-restart.json"
RESULT_FILENAME = "production-runtime-smoke-latest.json"

_VALID_HEARTBEAT_STATES = {"healthy", "degraded"}
_VALID_PUBLIC_STATES = {"available", "degraded"}
_VALID_REPORT_STATES = {
    "pending_transactions",
    "no_transaction_recommended",
    "awaiting_cio_construction",
}

ProviderProbe = Callable[[], Mapping[str, object]]
BackupProbe = Callable[[], Mapping[str, object]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _data_root(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    return Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()


def pre_restart_snapshot_path(environ: Mapping[str, str] | None = None) -> Path:
    return _data_root(environ) / SNAPSHOT_FILENAME


def latest_result_path(environ: Mapping[str, str] | None = None) -> Path:
    return _data_root(environ) / RESULT_FILENAME


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: object, *, now: datetime) -> float | None:
    timestamp = _parse_timestamp(value)
    if timestamp is None:
        return None
    return (now - timestamp).total_seconds()


def _process_start_marker() -> str:
    """Return a non-secret marker that changes when this Streamlit process restarts."""

    try:
        fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
        start_ticks = fields[21]
    except (OSError, IndexError):
        start_ticks = "unavailable"
    material = f"pid={os.getpid()};start_ticks={start_ticks}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _database_summary(path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "filename": path.name,
        "exists": path.is_file(),
        "integrity": None,
        "schema_fingerprint": None,
        "table_row_counts": {},
    }
    if not path.is_file():
        return summary

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        summary["integrity"] = integrity_row[0] if integrity_row else None
        schema_rows = connection.execute(
            """
            SELECT type, name, tbl_name, COALESCE(sql, '')
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        summary["schema_fingerprint"] = hashlib.sha256(
            json.dumps(schema_rows, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        tables = [row[1] for row in schema_rows if row[0] == "table"]
        counts: dict[str, int] = {}
        for table in tables:
            escaped = str(table).replace('"', '""')
            counts[str(table)] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0]
            )
        summary["table_row_counts"] = counts
    finally:
        connection.close()
    return summary


def _database_set(root: Path) -> dict[str, dict[str, object]]:
    return {
        "portfolio": _database_summary(root / "canonical_portfolio.db"),
        "journal": _database_summary(root / "institutional_journal.db"),
    }


def _rows_preserved(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    before_counts = before.get("table_row_counts")
    after_counts = after.get("table_row_counts")
    if not isinstance(before_counts, Mapping) or not isinstance(after_counts, Mapping):
        return False, ["table row-count metadata is unavailable"]
    for table, prior_count in before_counts.items():
        current_count = after_counts.get(table)
        if current_count is None:
            failures.append(f"table disappeared: {table}")
            continue
        try:
            if int(current_count) < int(prior_count):
                failures.append(
                    f"{table} decreased from {int(prior_count)} to {int(current_count)} rows"
                )
        except (TypeError, ValueError):
            failures.append(f"invalid row count for table: {table}")
    return not failures, failures


def capture_pre_restart_snapshot(
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    process_marker: str | None = None,
) -> dict[str, object]:
    timestamp = _aware_utc(now or _utc_now())
    values = os.environ if environ is None else environ
    root = _data_root(values)
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA,
        "captured_at": timestamp.isoformat(),
        "release": (
            values.get("CAPITAL_INTELLIGENCE_RELEASE")
            or values.get("RENDER_GIT_COMMIT")
            or "unknown"
        ),
        "persistent_canary": secrets.token_hex(24),
        "process_start_marker": process_marker or _process_start_marker(),
        "databases": _database_set(root),
        "paper_only": True,
        "real_money_authorized": False,
    }
    _atomic_json(pre_restart_snapshot_path(values), snapshot)
    return snapshot


def load_pre_restart_snapshot(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    snapshot = _load_json(pre_restart_snapshot_path(environ))
    if snapshot is None or snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
        return None
    return snapshot


def _latest_execution_attempt(root: Path) -> dict[str, Any] | None:
    directory = root / "paper_execution_artifacts"
    try:
        ranked = ordered_json_artifacts(
            directory.glob("*.status.json"),
            timestamp_fields=("attempted_at",),
            identifier_fields=("execution_identifier",),
        )
    except OSError:
        return None
    for _, payload in ranked:
        return {
            "state": payload.get("state"),
            "attempted_at": payload.get("attempted_at"),
            "exit_code": payload.get("exit_code"),
            "execution_identifier": payload.get("execution_identifier"),
            "paper_only": True,
            "real_money_authorized": False,
        }
    return None


def _default_provider_probe() -> Mapping[str, object]:
    result: dict[str, object] = {
        "alpaca_iex": {"status": "failed"},
        "fred": {"status": "failed"},
    }
    try:
        from operations.free_paper_pilot import (
            DEFAULT_UNIVERSE_PATH,
            load_free_paper_pilot_universe,
        )
        from providers.alpaca_paper import AlpacaPaperClient, AlpacaPaperSettings

        universe = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
        instruments = tuple(universe.instruments)
        client = AlpacaPaperClient(AlpacaPaperSettings.from_env())
        account = client.account()
        clock = client.clock()
        quotes = client.latest_quotes([item.symbol for item in instruments])
        quote_times = [
            timestamp
            for timestamp in (
                _parse_timestamp(payload.get("t"))
                for payload in quotes.values()
                if isinstance(payload, Mapping)
            )
            if timestamp is not None
        ]
        latest_quote = max(quote_times) if quote_times else None
        result["alpaca_iex"] = {
            "status": "connected",
            "account_status": str(account.get("status", "unavailable")),
            "market_open": clock.get("is_open") is True,
            "quote_count": len(quotes),
            "expected_quote_count": len(instruments),
            "latest_quote_at": latest_quote.isoformat() if latest_quote else None,
        }
    except Exception as error:
        result["alpaca_iex"] = {
            "status": "failed",
            "error_type": type(error).__name__,
        }

    try:
        from providers.fred import FREDProvider

        observation = FREDProvider().get_latest_value("DGS10")
        result["fred"] = {
            "status": "connected",
            "series": "DGS10",
            "observation_date": observation.date,
        }
    except Exception as error:
        result["fred"] = {
            "status": "failed",
            "error_type": type(error).__name__,
        }
    return result


def _default_backup_probe() -> Mapping[str, object]:
    try:
        from run_backup import build_manager

        manager = build_manager()
        healthy, detail, archive = manager.latest_backup_health(
            maximum_age_seconds=48 * 3600,
        )
    except Exception as error:
        return {
            "status": "blocked",
            "detail": "Backup health evaluation failed.",
            "error_type": type(error).__name__,
            "archive": None,
        }
    return {
        "status": "healthy" if healthy else "blocked",
        "detail": detail,
        "archive": archive.name if archive is not None else None,
    }


def create_encrypted_backup_now(
    *,
    manager_factory: Callable[[], object] | None = None,
) -> dict[str, object]:
    try:
        if manager_factory is None:
            from run_backup import build_manager

            manager = build_manager()
        else:
            manager = manager_factory()
        result = manager.create_backup()
    except Exception as error:
        return {
            "status": "blocked",
            "detail": "Encrypted backup creation failed.",
            "error_type": type(error).__name__,
            "real_money_authorized": False,
        }
    return {
        "status": "completed",
        "archive": result.archive.name,
        "encrypted": bool(result.encrypted),
        "database_count": len(result.manifest.get("files", [])),
        "schema_version": result.manifest.get("schema_version"),
        "real_money_authorized": False,
    }


def evaluate_runtime_smoke_test(
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    process_marker: str | None = None,
    provider_probe: ProviderProbe | None = None,
    backup_probe: BackupProbe | None = None,
    maximum_heartbeat_age_seconds: int = 180,
    maximum_public_state_age_seconds: int = 7200,
    maximum_report_age_seconds: int = 180,
) -> dict[str, object]:
    if maximum_heartbeat_age_seconds < 10:
        raise ValueError("maximum heartbeat age must be at least 10 seconds")
    if maximum_public_state_age_seconds < 300:
        raise ValueError("maximum public-state age must be at least 300 seconds")
    if maximum_report_age_seconds < 10:
        raise ValueError("maximum report age must be at least 10 seconds")

    timestamp = _aware_utc(now or _utc_now())
    values = os.environ if environ is None else environ
    root = _data_root(values)
    before = load_pre_restart_snapshot(values)
    after_databases = _database_set(root)
    current_marker = process_marker or _process_start_marker()

    persistence_failures: list[str] = []
    restart_observed = bool(
        before
        and before.get("process_start_marker")
        and before.get("process_start_marker") != current_marker
    )
    if not restart_observed:
        persistence_failures.append("a process restart has not been observed since capture")

    for name in ("portfolio", "journal"):
        current = after_databases[name]
        if current.get("integrity") != "ok":
            persistence_failures.append(f"{name} database integrity is not ok")
            continue
        prior_databases = before.get("databases") if isinstance(before, Mapping) else None
        prior = prior_databases.get(name) if isinstance(prior_databases, Mapping) else None
        if not isinstance(prior, Mapping):
            persistence_failures.append(f"pre-restart {name} database summary is unavailable")
            continue
        preserved, failures = _rows_preserved(prior, current)
        if not preserved:
            persistence_failures.extend(f"{name}: {failure}" for failure in failures)
        if prior.get("schema_fingerprint") != current.get("schema_fingerprint"):
            persistence_failures.append(f"{name} database schema changed across restart")

    heartbeat = _load_json(root / "worker-heartbeat.json")
    heartbeat_age = _age_seconds(
        heartbeat.get("observed_at") if heartbeat else None,
        now=timestamp,
    )
    cio_report = _load_json(root / "cio_reports" / "pending_transactions_latest.json")
    report_age = _age_seconds(
        cio_report.get("generated_at") if cio_report else None,
        now=timestamp,
    )
    heartbeat_and_cycle_current = bool(
        heartbeat
        and heartbeat.get("status") in _VALID_HEARTBEAT_STATES
        and isinstance(heartbeat.get("cycle_key"), str)
        and heartbeat.get("cycle_key")
        and heartbeat_age is not None
        and -5 <= heartbeat_age <= maximum_heartbeat_age_seconds
        and cio_report
        and cio_report.get("portfolio_code") == "COMPOUNDING"
        and cio_report.get("report_state") in _VALID_REPORT_STATES
        and report_age is not None
        and -5 <= report_age <= maximum_report_age_seconds
    )

    public_state = _load_json(root / "public-live-information-runtime-state.json")
    public_age = _age_seconds(
        public_state.get("completed_at") if public_state else None,
        now=timestamp,
    )
    providers = dict((provider_probe or _default_provider_probe)())
    alpaca = providers.get("alpaca_iex")
    fred = providers.get("fred")
    provider_observations_current = bool(
        isinstance(alpaca, Mapping)
        and alpaca.get("status") == "connected"
        and str(alpaca.get("account_status", "")).upper() == "ACTIVE"
        and int(alpaca.get("quote_count", 0) or 0) > 0
        and int(alpaca.get("quote_count", 0) or 0)
        == int(alpaca.get("expected_quote_count", 0) or 0)
        and isinstance(fred, Mapping)
        and fred.get("status") == "connected"
        and public_state
        and public_state.get("state") in _VALID_PUBLIC_STATES
        and public_state.get("required_sources_ready") is True
        and public_age is not None
        and -5 <= public_age <= maximum_public_state_age_seconds
    )

    latest_execution = _latest_execution_attempt(root)
    explicit_no_action = bool(
        cio_report
        and cio_report.get("report_state") == "no_transaction_recommended"
        and cio_report.get("comparative_cio_decision_complete") is True
        and int(cio_report.get("transaction_count", 0) or 0) == 0
    )
    completed_execution = bool(
        cio_report
        and cio_report.get("execution_state") == "completed"
        and latest_execution
        and latest_execution.get("state") == "completed"
        and latest_execution.get("execution_identifier")
    )
    governed_outcome_recorded = bool(
        cio_report
        and cio_report.get("portfolio_code") == "COMPOUNDING"
        and cio_report.get("paper_only") is True
        and cio_report.get("real_money_authorized") is False
        and (explicit_no_action or completed_execution)
    )

    backup = dict((backup_probe or _default_backup_probe)())
    encrypted_backup_healthy = bool(
        backup.get("status") == "healthy" and backup.get("archive")
    )

    checks = {
        "persistent_state_survived_restart": not persistence_failures and bool(before),
        "operator_heartbeat_and_cio_cycle_current": heartbeat_and_cycle_current,
        "provider_market_observations_current": provider_observations_current,
        "governed_paper_outcome_recorded": governed_outcome_recorded,
        "encrypted_backup_healthy": encrypted_backup_healthy,
    }
    result: dict[str, object] = {
        "schema_version": RESULT_SCHEMA,
        "evaluated_at": timestamp.isoformat(),
        "overall_status": "PASS" if all(checks.values()) else "CONDITIONAL_OR_FAILED",
        "checks": checks,
        "persistence": {
            "snapshot_present": before is not None,
            "restart_observed": restart_observed,
            "failures": persistence_failures,
            "databases": after_databases,
        },
        "heartbeat": {
            "status": heartbeat.get("status") if heartbeat else None,
            "observed_at": heartbeat.get("observed_at") if heartbeat else None,
            "age_seconds": heartbeat_age,
            "cycle_key": heartbeat.get("cycle_key") if heartbeat else None,
            "detail": heartbeat.get("detail") if heartbeat else None,
        },
        "cio_report": {
            "generated_at": cio_report.get("generated_at") if cio_report else None,
            "age_seconds": report_age,
            "portfolio_code": cio_report.get("portfolio_code") if cio_report else None,
            "report_state": cio_report.get("report_state") if cio_report else None,
            "execution_state": cio_report.get("execution_state") if cio_report else None,
            "decision_identifier": cio_report.get("decision_identifier") if cio_report else None,
            "transaction_count": cio_report.get("transaction_count") if cio_report else None,
            "summary": cio_report.get("summary") if cio_report else None,
        },
        "public_live_information": {
            "state": public_state.get("state") if public_state else None,
            "completed_at": public_state.get("completed_at") if public_state else None,
            "age_seconds": public_age,
            "required_sources_ready": (
                public_state.get("required_sources_ready") if public_state else None
            ),
            "source_count": public_state.get("source_count") if public_state else None,
            "failed_source_count": (
                public_state.get("failed_source_count") if public_state else None
            ),
        },
        "provider_connections": providers,
        "latest_paper_execution_attempt": latest_execution,
        "backup_health": backup,
        "paper_only": True,
        "real_money_authorized": False,
    }
    _atomic_json(latest_result_path(values), result)
    return result


__all__ = [
    "RESULT_FILENAME",
    "RESULT_SCHEMA",
    "SNAPSHOT_FILENAME",
    "SNAPSHOT_SCHEMA",
    "capture_pre_restart_snapshot",
    "create_encrypted_backup_now",
    "evaluate_runtime_smoke_test",
    "latest_result_path",
    "load_pre_restart_snapshot",
    "pre_restart_snapshot_path",
]
from operations.artifact_ordering import ordered_json_artifacts
