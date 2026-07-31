"""Create encrypted, verified backups of all active canonical authorities."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations import (
    RETIRED_BACKUP_AUTHORITIES,
    BackupError,
    OperationalSettings,
    SQLiteBackupManager,
    WorkerHeartbeatStore,
    build_canonical_backup_registry,
    component_heartbeat_path,
    configure_logging,
)


_ACTIVATION_STATE_SCHEMA = "canonical-backup-authority-activation.v1"


def _boolean(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _activation_state_path(values: Mapping[str, str]) -> Path:
    configured = values.get(
        "CAPITAL_INTELLIGENCE_BACKUP_AUTHORITY_ACTIVATION_STATE",
        "",
    ).strip()
    if configured:
        return Path(configured).expanduser()
    data_directory = Path(
        values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return data_directory / "backup-authority-activation.json"


def _load_activated_sources(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"backup authority activation state is invalid: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError("backup authority activation state must be a JSON object")
    if payload.get("schema_version") != _ACTIVATION_STATE_SCHEMA:
        raise ValueError("unsupported backup authority activation state schema")
    names = payload.get("activated_logical_names")
    if not isinstance(names, list) or any(
        not isinstance(item, str) or not item.strip() for item in names
    ):
        raise ValueError(
            "backup authority activation state must contain string logical names"
        )
    normalized = {item.strip() for item in names}
    if len(normalized) != len(names):
        raise ValueError("backup authority activation state contains duplicate names")
    return normalized


def _write_activated_sources(path: Path, names: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _ACTIVATION_STATE_SCHEMA,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "activated_logical_names": list(names),
        "policy": (
            "A canonical authority becomes permanently required after its SQLite "
            "database is first observed in this persistent deployment."
        ),
        "real_money_authorized": False,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _required_sources_for_deployment(
    *,
    registry,
    values: Mapping[str, str],
) -> tuple[str, ...]:
    activation_aware = _boolean(
        values.get("CAPITAL_INTELLIGENCE_BACKUP_ACTIVATION_AWARE"),
        default=False,
    )
    if not activation_aware:
        return registry.required_logical_names

    state_path = _activation_state_path(values)
    previously_activated = _load_activated_sources(state_path)
    defined_required = set(registry.required_logical_names)
    unknown = previously_activated - defined_required
    if unknown:
        raise ValueError(
            "backup authority activation state references unknown authorities: "
            f"{sorted(unknown)}"
        )

    currently_available = {
        logical_name
        for logical_name, path in registry.paths
        if logical_name in defined_required and path.is_file()
    }
    activated = previously_activated | currently_available
    ordered = tuple(
        logical_name
        for logical_name in registry.required_logical_names
        if logical_name in activated
    )
    if activated != previously_activated or not state_path.exists():
        _write_activated_sources(state_path, ordered)
    return ordered


def build_manager(
    environ: Mapping[str, str] | None = None,
) -> SQLiteBackupManager:
    values = os.environ if environ is None else environ
    operational = OperationalSettings.from_env(values)
    registry = build_canonical_backup_registry(values)
    required_sources = _required_sources_for_deployment(
        registry=registry,
        values=values,
    )
    return SQLiteBackupManager(
        registry.sources,
        operational.backup_directory,
        encryption_key=operational.backup_encryption_key,
        require_encryption=operational.require_encrypted_backups,
        retention_days=operational.backup_retention_days,
        required_sources=required_sources,
        source_metadata=registry.metadata,
        prohibited_sources=tuple(sorted(RETIRED_BACKUP_AUTHORITIES)),
        baseline_identifier=values.get(
            "CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER"
        ),
        process_version=values.get(
            "CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION"
        ),
        code_version=(
            values.get("CAPITAL_INTELLIGENCE_RELEASE")
            or values.get("GITHUB_SHA")
            or "unknown"
        ),
        registry_schema_version=registry.schema_version,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Back up every active canonical Capital Intelligence authority."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--loop",
        action="store_true",
        help="Run backups continuously.",
    )
    mode.add_argument(
        "--healthcheck",
        action="store_true",
        help=(
            "Verify that the newest backup is recent, encrypted when required, "
            "complete, and valid."
        ),
    )
    mode.add_argument(
        "--validate-sources",
        action="store_true",
        help="Validate the complete active authority set without creating an archive.",
    )
    parser.add_argument("--interval-hours", type=int, default=None)
    parser.add_argument("--maximum-age-hours", type=int, default=None)
    parser.add_argument(
        "--initial-delay-seconds",
        type=int,
        default=0,
        help=(
            "Delay the first loop backup so sibling services can initialize their "
            "persistent authorities."
        ),
    )
    return parser


def _configuration_error(error: Exception) -> dict[str, object]:
    return {
        "status": "blocked",
        "classification": "configuration",
        "error": str(error),
        "real_money_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 0 <= args.initial_delay_seconds <= 3600:
        parser.error("--initial-delay-seconds must be between 0 and 3600")

    operational = OperationalSettings.from_env()
    heartbeat = WorkerHeartbeatStore(
        component_heartbeat_path(
            Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")),
            "encrypted-backup",
        )
    )
    configure_logging(operational)
    logger = logging.getLogger("capital_intelligence.backup")

    if args.validate_sources or args.healthcheck:
        try:
            manager = build_manager()
        except (OSError, TypeError, ValueError) as error:
            print(json.dumps(_configuration_error(error), indent=2, sort_keys=True))
            return 4

        if args.validate_sources:
            report = manager.validate_sources()
            report["real_money_authorized"] = False
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["status"] == "valid" else 3

        maximum_age_hours = args.maximum_age_hours or max(
            1,
            operational.backup_interval_hours * 2,
        )
        if maximum_age_hours < 1:
            parser.error("--maximum-age-hours must be positive")
        healthy, detail, archive = manager.latest_backup_health(
            maximum_age_seconds=maximum_age_hours * 3600,
        )
        print(
            json.dumps(
                {
                    "status": "healthy" if healthy else "blocked",
                    "detail": detail,
                    "archive": None if archive is None else str(archive),
                    "maximum_age_hours": maximum_age_hours,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if healthy else 1

    interval = args.interval_hours or operational.backup_interval_hours
    if interval < 1:
        parser.error("--interval-hours must be positive")
    if args.loop and args.initial_delay_seconds:
        time.sleep(args.initial_delay_seconds)

    while True:
        heartbeat.write("starting", detail="encrypted canonical backup started")
        try:
            manager = build_manager()
            result = manager.create_backup()
        except (OSError, TypeError, ValueError) as error:
            heartbeat.write("failed", detail=str(error)[:1000])
            logger.exception("canonical backup configuration failed")
            if not args.loop:
                print(json.dumps(_configuration_error(error), indent=2, sort_keys=True))
                return 4
        except BackupError:
            heartbeat.write("failed", detail="canonical encrypted backup failed")
            logger.exception("canonical backup failed")
            if not args.loop:
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "classification": "backup",
                            "error": "canonical backup failed; see structured logs",
                            "real_money_authorized": False,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 1
        else:
            heartbeat.write(
                "healthy",
                cycle_key=str(result.manifest.get("created_at") or result.archive.name),
                detail=f"encrypted backup completed: {result.archive.name}",
            )
            logger.info(
                "canonical backup completed",
                extra={
                    "archive": str(result.archive),
                    "encrypted": result.encrypted,
                    "database_count": len(result.manifest["files"]),
                    "schema_version": result.manifest["schema_version"],
                },
            )
            if not args.loop:
                print(
                    json.dumps(
                        {
                            "status": "completed",
                            "archive": str(result.archive),
                            "encrypted": result.encrypted,
                            "database_count": len(result.manifest["files"]),
                            "schema_version": result.manifest["schema_version"],
                            "required_logical_names": result.manifest.get(
                                "required_logical_names",
                                [],
                            ),
                            "baseline_identifier": result.manifest.get(
                                "baseline_identifier"
                            ),
                            "process_version": result.manifest.get(
                                "process_version"
                            ),
                            "code_version": result.manifest.get("code_version"),
                            "real_money_authorized": False,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
        time.sleep(interval * 3600)


if __name__ == "__main__":
    raise SystemExit(main())
