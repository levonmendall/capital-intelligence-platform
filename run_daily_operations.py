"""Run the complete canonical daily investment process as one fenced workflow."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from operations import (
    CANONICAL_DAILY_STAGE_ORDER,
    CanonicalDailyOperationRequest,
    CanonicalDailyStage,
    CommandStageRunner,
    DailyOperationLeaseError,
    DailyOperationStatus,
    LeasedCanonicalDailyOperationsOrchestrator,
    LeasedSQLiteCanonicalDailyOperationsStore,
    OperationalSettings,
    SQLiteCanonicalDailyOperationsStore,
    StageRetryPolicy,
    WorkerHeartbeatStore,
    operation_result_to_dict,
)
from operations.stage_bindings import validate_stage_bindings


def _aware(value: str | None, *, default: datetime) -> datetime:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed


def _load_plan(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load daily operations plan {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("daily operations plan must encode an object")
    schema = payload.get("schema_version")
    if schema not in {
        "canonical-daily-operations.v1",
        "canonical-daily-operations.v2",
    }:
        raise ValueError(
            "daily operations plan must use canonical-daily-operations.v1 or v2"
        )
    identifier = payload.get("identifier")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("daily operations plan requires an identifier")
    if schema == "canonical-daily-operations.v2" and payload.get(
        "lease_required"
    ) is not True:
        raise ValueError("v2 daily operations plan must require leases")
    stages = payload.get("stages")
    if not isinstance(stages, Mapping):
        raise ValueError("daily operations plan requires a stages object")
    expected = {stage.value for stage in CANONICAL_DAILY_STAGE_ORDER}
    actual = set(stages)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            "daily operations plan must configure every stage: "
            f"missing={missing} extra={extra}"
        )
    return payload


def _expand_argument(value: str) -> str:
    expanded = os.path.expandvars(value)
    if "$" in expanded:
        raise ValueError(f"daily operation argument has unresolved environment value: {value}")
    return expanded


def _stage_configuration(
    payload: Mapping[str, Any],
) -> tuple[
    dict[CanonicalDailyStage, CommandStageRunner],
    dict[CanonicalDailyStage, StageRetryPolicy],
]:
    raw_stages = payload["stages"]
    assert isinstance(raw_stages, Mapping)
    runners: dict[CanonicalDailyStage, CommandStageRunner] = {}
    policies: dict[CanonicalDailyStage, StageRetryPolicy] = {}
    for stage in CANONICAL_DAILY_STAGE_ORDER:
        value = raw_stages[stage.value]
        if not isinstance(value, Mapping):
            raise ValueError(f"stage {stage.value} configuration must be an object")
        module = value.get("module")
        argv = value.get("argv")
        output_fields = value.get("output_fields")
        retryable_exit_codes = value.get("retryable_exit_codes", [])
        if not isinstance(module, str) or not module.strip():
            raise ValueError(f"stage {stage.value} requires module")
        if not isinstance(argv, list) or not all(
            isinstance(item, str) for item in argv
        ):
            raise ValueError(f"stage {stage.value} argv must be a string list")
        if not isinstance(output_fields, list) or not all(
            isinstance(item, str) for item in output_fields
        ) or not output_fields:
            raise ValueError(
                f"stage {stage.value} output_fields must be a non-empty string list"
            )
        if not isinstance(retryable_exit_codes, list) or not all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in retryable_exit_codes
        ):
            raise ValueError(
                f"stage {stage.value} retryable_exit_codes must be integers"
            )
        runners[stage] = CommandStageRunner(
            name=str(value.get("name") or f"COMMAND:{module}"),
            module=module,
            argv=tuple(_expand_argument(item) for item in argv),
            output_fields=tuple(output_fields),
            retryable_exit_codes=tuple(retryable_exit_codes),
        )
        retry = value.get("retry", {})
        if not isinstance(retry, Mapping):
            raise ValueError(f"stage {stage.value} retry must be an object")
        policies[stage] = StageRetryPolicy(
            maximum_attempts=int(retry.get("maximum_attempts", 3)),
            initial_backoff_seconds=float(
                retry.get("initial_backoff_seconds", 1.0)
            ),
            multiplier=float(retry.get("multiplier", 2.0)),
            maximum_backoff_seconds=float(
                retry.get("maximum_backoff_seconds", 60.0)
            ),
        )
    return runners, policies


def _binding_path_from_stage(stage_value: Mapping[str, Any]) -> Path | None:
    if stage_value.get("module") != "run_daily_stage_adapter":
        return None
    argv = stage_value.get("argv")
    if not isinstance(argv, list):
        return None
    for index, item in enumerate(argv[:-1]):
        if item == "--bindings":
            return Path(_expand_argument(str(argv[index + 1]))).expanduser()
    raise ValueError("run_daily_stage_adapter requires --bindings in every stage")


def _validate_plan_runtime(
    payload: Mapping[str, Any],
) -> dict[str, object]:
    runners, policies = _stage_configuration(payload)
    raw_stages = payload["stages"]
    assert isinstance(raw_stages, Mapping)
    binding_paths: set[Path] = set()
    for stage, runner in runners.items():
        try:
            main = getattr(importlib.import_module(runner.module), "main")
        except (ImportError, AttributeError) as error:
            raise ValueError(
                f"stage {stage.value} cannot import command module {runner.module!r}"
            ) from error
        if not callable(main):
            raise ValueError(
                f"stage {stage.value} command module has no callable main"
            )
        path = _binding_path_from_stage(raw_stages[stage.value])
        if path is not None:
            binding_paths.add(path)
    binding_reports = [validate_stage_bindings(path) for path in sorted(binding_paths)]
    return {
        "status": "valid",
        "identifier": payload["identifier"],
        "schema_version": payload["schema_version"],
        "lease_required": True,
        "stage_count": len(runners),
        "stages": [stage.value for stage in CANONICAL_DAILY_STAGE_ORDER],
        "maximum_attempts": {
            stage.value: policies[stage].maximum_attempts
            for stage in CANONICAL_DAILY_STAGE_ORDER
        },
        "binding_reports": binding_reports,
        "real_money_authorized": False,
    }


def _operation_boundary(
    *,
    now: datetime,
    timezone_name: str,
    operation_hour: int,
) -> tuple[date, datetime]:
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    operation_date = local_now.date()
    scheduled = datetime.combine(
        operation_date,
        clock_time(hour=operation_hour),
        tzinfo=zone,
    )
    return operation_date, scheduled


def _request(
    args: argparse.Namespace,
    *,
    plan: Mapping[str, Any],
    now: datetime,
) -> CanonicalDailyOperationRequest:
    operation_date, default_boundary = _operation_boundary(
        now=now,
        timezone_name=args.operation_timezone,
        operation_hour=args.operation_hour,
    )
    scheduled_for = _aware(args.scheduled_for, default=default_boundary)
    decision_timestamp = _aware(args.decision_timestamp, default=scheduled_for)
    knowledge_cutoff = _aware(args.knowledge_cutoff, default=decision_timestamp)
    started_at = _aware(args.started_at, default=now)
    process_version = (
        args.process_version
        or os.getenv("CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION")
        or "Capital Intelligence Investment Process v1.0-draft"
    )
    code_version = (
        args.code_version
        or os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
        or os.getenv("GITHUB_SHA")
        or "unknown"
    )
    portfolio_code = args.portfolio_code.upper()
    identifier = args.operation_id or (
        f"canonical-daily:{portfolio_code}:{operation_date.isoformat()}"
    )
    idempotency_key = args.idempotency_key or (
        f"canonical-daily:{portfolio_code}:{operation_date.isoformat()}:"
        f"{process_version}"
    )
    supplied_identifiers = list(args.input_identifier or ())
    if not supplied_identifiers:
        plan_identifier = str(
            plan.get("identifier") or "canonical-daily-operations-plan"
        )
        supplied_identifiers.append(f"plan:{plan_identifier}")
    if args.test_baseline_identifier:
        baseline = args.test_baseline_identifier.strip()
        if not baseline:
            raise ValueError("test baseline identifier cannot be empty")
        supplied_identifiers.append(baseline)
    input_identifiers = tuple(dict.fromkeys(supplied_identifiers))
    return CanonicalDailyOperationRequest(
        identifier=identifier,
        idempotency_key=idempotency_key,
        operation_date=operation_date,
        scheduled_for=scheduled_for,
        decision_timestamp=decision_timestamp,
        knowledge_cutoff=knowledge_cutoff,
        started_at=started_at,
        portfolio_code=portfolio_code,
        process_version=process_version,
        code_version=code_version,
        input_identifiers=input_identifiers,
    )


def _post_operation_publisher(args: argparse.Namespace):
    from governance import SQLiteReadinessEvidenceStore
    from operations import (
        SQLiteOperationalIncidentStore,
        SQLiteOperationalSLOStore,
        SQLiteResilienceExerciseStore,
    )
    from operations.post_operation import PostOperationReadinessPublisher
    from operations.readiness import (
        OperationalReadinessAssembler,
        OperationalReadinessAssemblyPolicy,
    )

    return PostOperationReadinessPublisher(
        assembler=OperationalReadinessAssembler(
            daily_store=SQLiteCanonicalDailyOperationsStore(args.database),
            slo_store=SQLiteOperationalSLOStore(args.slo_database),
            resilience_store=SQLiteResilienceExerciseStore(
                args.resilience_database
            ),
            incident_store=SQLiteOperationalIncidentStore(
                args.incident_database
            ),
            readiness_store=SQLiteReadinessEvidenceStore(
                args.readiness_evidence_database
            ),
            policy=OperationalReadinessAssemblyPolicy(
                maximum_daily_operation_age=timedelta(
                    hours=args.maximum_daily_age_hours
                ),
                maximum_slo_age=timedelta(
                    hours=args.maximum_slo_age_hours
                ),
                maximum_resilience_report_age=timedelta(
                    days=args.maximum_resilience_age_days
                ),
            ),
        ),
        baseline_identifier=args.test_baseline_identifier,
    )


def _default_worker_identifier() -> str:
    return (
        os.getenv("CAPITAL_INTELLIGENCE_DAILY_WORKER_IDENTIFIER")
        or f"{socket.gethostname()}:{os.getpid()}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_DAILY_OPERATION_PLAN",
            "deploy/canonical-daily-operations.json",
        ),
        help="Complete canonical 12-stage plan JSON.",
    )
    parser.add_argument("--validate-plan", action="store_true")
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_DAILY_OPERATION_DATABASE",
            "database/canonical_daily_operations.db",
        ),
    )
    parser.add_argument(
        "--worker-identifier",
        default=_default_worker_identifier(),
    )
    parser.add_argument(
        "--lease-seconds",
        type=float,
        default=float(
            os.getenv("CAPITAL_INTELLIGENCE_DAILY_LEASE_SECONDS", "120")
        ),
    )
    parser.add_argument(
        "--lease-heartbeat-seconds",
        type=float,
        default=float(
            os.getenv(
                "CAPITAL_INTELLIGENCE_DAILY_LEASE_HEARTBEAT_SECONDS",
                "15",
            )
        ),
    )
    parser.add_argument("--operation-id")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--scheduled-for")
    parser.add_argument("--decision-timestamp")
    parser.add_argument("--knowledge-cutoff")
    parser.add_argument("--started-at")
    parser.add_argument("--portfolio-code", default="COMPOUNDING")
    parser.add_argument("--process-version")
    parser.add_argument("--code-version")
    parser.add_argument(
        "--input-identifier",
        action="append",
        help="Initial canonical input identifier. May be repeated.",
    )
    parser.add_argument(
        "--test-baseline-identifier",
        default=os.getenv("CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER"),
        help=(
            "Immutable test baseline to bind into the operation and use for "
            "post-terminal operational-readiness publication."
        ),
    )
    parser.add_argument(
        "--slo-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_OPERATIONAL_SLO_DATABASE",
            "database/operational_slos.db",
        ),
    )
    parser.add_argument(
        "--resilience-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_RESILIENCE_DATABASE",
            "database/resilience_exercises.db",
        ),
    )
    parser.add_argument(
        "--incident-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_OPERATIONAL_INCIDENT_DATABASE",
            "database/operational_incidents.db",
        ),
    )
    parser.add_argument(
        "--readiness-evidence-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PRODUCT_READINESS_EVIDENCE_DATABASE",
            "database/product_readiness_evidence.db",
        ),
    )
    parser.add_argument("--maximum-daily-age-hours", type=float, default=24.0)
    parser.add_argument("--maximum-slo-age-hours", type=float, default=24.0)
    parser.add_argument("--maximum-resilience-age-days", type=float, default=30.0)
    parser.add_argument(
        "--require-clean-operational-readiness",
        action="store_true",
    )
    parser.add_argument(
        "--operation-timezone",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_DAILY_OPERATION_TIMEZONE",
            "America/New_York",
        ),
    )
    parser.add_argument(
        "--operation-hour",
        type=int,
        default=int(
            os.getenv("CAPITAL_INTELLIGENCE_DAILY_OPERATION_HOUR", "7")
        ),
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=int(
            os.getenv("CAPITAL_INTELLIGENCE_DAILY_OPERATION_POLL_SECONDS", "60")
        ),
    )
    return parser


def _run_once(
    args: argparse.Namespace,
    *,
    plan: Mapping[str, Any],
    heartbeat: WorkerHeartbeatStore,
) -> int:
    now = datetime.now(timezone.utc)
    request = _request(args, plan=plan, now=now)
    heartbeat.write(
        "starting",
        cycle_key=request.idempotency_key,
        detail=(
            "canonical daily operation lease requested by "
            f"{args.worker_identifier}"
        ),
        observed_at=now,
    )
    runners, policies = _stage_configuration(plan)
    store = LeasedSQLiteCanonicalDailyOperationsStore(
        args.database,
        worker_identifier=args.worker_identifier,
        lease_duration=timedelta(seconds=args.lease_seconds),
    )
    orchestrator = LeasedCanonicalDailyOperationsOrchestrator(
        store=store,
        runners=runners,
        retry_policies=policies,
        heartbeat_interval_seconds=args.lease_heartbeat_seconds,
    )
    try:
        result = orchestrator.run(request)
    except DailyOperationLeaseError as error:
        payload = {
            "identifier": request.identifier,
            "idempotency_key": request.idempotency_key,
            "status": "lease_not_acquired",
            "worker_identifier": args.worker_identifier,
            "detail": str(error),
            "real_money_authorized": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        heartbeat.write(
            "healthy",
            cycle_key=request.idempotency_key,
            detail="another worker owns the active daily-operation lease",
        )
        return 0
    payload = operation_result_to_dict(result)
    payload["worker_identifier"] = args.worker_identifier
    payload["lease_status"] = store.lease_status(request.identifier)
    publication = None
    if args.test_baseline_identifier:
        try:
            publication = _post_operation_publisher(args).publish(
                request,
                result,
                published_at=datetime.now(timezone.utc),
            )
            payload["operational_readiness"] = publication.to_dict()
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            payload["operational_readiness"] = {
                "status": "publication_failed",
                "error": str(error),
                "real_money_authorized": False,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            heartbeat.write(
                "failed",
                cycle_key=request.idempotency_key,
                detail="post-operation readiness publication failed",
            )
            return 4
    print(json.dumps(payload, indent=2, sort_keys=True))

    if result.status is not DailyOperationStatus.COMPLETED:
        heartbeat.write(
            "failed",
            cycle_key=request.idempotency_key,
            detail=(
                "canonical daily operation failed"
                if result.failed_stage is None
                else f"canonical daily operation failed at {result.failed_stage.value}"
            ),
        )
        return 3
    if (
        args.require_clean_operational_readiness
        and publication is not None
        and not publication.clean
    ):
        heartbeat.write(
            "failed",
            cycle_key=request.idempotency_key,
            detail=(
                "canonical daily operation completed but operational readiness "
                "contains blockers"
            ),
        )
        return 3
    heartbeat.write(
        "healthy",
        cycle_key=request.idempotency_key,
        detail=(
            "canonical daily operation and operational readiness completed"
            if publication is not None and publication.clean
            else "canonical daily operation completed"
        ),
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 0 <= args.operation_hour <= 23:
        parser.error("--operation-hour must be between 0 and 23")
    if args.poll_seconds < 10:
        parser.error("--poll-seconds must be at least 10")
    if args.lease_seconds < 5:
        parser.error("--lease-seconds must be at least 5")
    if args.lease_heartbeat_seconds <= 0:
        parser.error("--lease-heartbeat-seconds must be positive")
    if args.lease_heartbeat_seconds >= args.lease_seconds / 2:
        parser.error(
            "--lease-heartbeat-seconds must be less than half --lease-seconds"
        )
    for name in (
        "maximum_daily_age_hours",
        "maximum_slo_age_hours",
        "maximum_resilience_age_days",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if (
        args.require_clean_operational_readiness
        and not args.test_baseline_identifier
    ):
        parser.error(
            "--require-clean-operational-readiness requires "
            "--test-baseline-identifier"
        )
    try:
        plan = _load_plan(Path(args.plan).expanduser())
        validation = _validate_plan_runtime(plan)
        if args.validate_plan:
            print(json.dumps(validation, indent=2, sort_keys=True))
            return 0
        settings = OperationalSettings.from_env()
        heartbeat = WorkerHeartbeatStore(settings.worker_heartbeat_path)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))

    if not args.loop:
        return _run_once(args, plan=plan, heartbeat=heartbeat)

    heartbeat.write(
        "starting",
        detail=f"canonical daily operations loop started: {args.worker_identifier}",
    )
    while True:
        now = datetime.now(timezone.utc)
        _, scheduled = _operation_boundary(
            now=now,
            timezone_name=args.operation_timezone,
            operation_hour=args.operation_hour,
        )
        if now >= scheduled.astimezone(timezone.utc):
            exit_code = _run_once(args, plan=plan, heartbeat=heartbeat)
            if exit_code != 0:
                time.sleep(args.poll_seconds)
                continue
        else:
            heartbeat.write(
                "healthy",
                detail=(
                    f"worker {args.worker_identifier} waiting for daily boundary "
                    f"{scheduled.isoformat()}"
                ),
            )
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
