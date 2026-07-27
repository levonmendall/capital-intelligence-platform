"""Run the complete canonical daily investment process as one durable workflow."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, time as clock_time, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from operations import (
    CANONICAL_DAILY_STAGE_ORDER,
    CanonicalDailyOperationRequest,
    CanonicalDailyOperationsOrchestrator,
    CanonicalDailyStage,
    CommandStageRunner,
    DailyOperationStatus,
    OperationalSettings,
    SQLiteCanonicalDailyOperationsStore,
    StageRetryPolicy,
    WorkerHeartbeatStore,
    operation_result_to_dict,
)


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
    if payload.get("schema_version") != "canonical-daily-operations.v1":
        raise ValueError(
            "daily operations plan must use canonical-daily-operations.v1"
        )
    stages = payload.get("stages")
    if not isinstance(stages, Mapping):
        raise ValueError("daily operations plan requires a stages object")
    expected = {stage.value for stage in CANONICAL_DAILY_STAGE_ORDER}
    actual = set(stages)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"daily operations plan must configure every stage: "
            f"missing={missing} extra={extra}"
        )
    return payload


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
        if not isinstance(module, str):
            raise ValueError(f"stage {stage.value} requires module")
        if not isinstance(argv, list) or not all(
            isinstance(item, str) for item in argv
        ):
            raise ValueError(f"stage {stage.value} argv must be a string list")
        if not isinstance(output_fields, list) or not all(
            isinstance(item, str) for item in output_fields
        ):
            raise ValueError(
                f"stage {stage.value} output_fields must be a string list"
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
            argv=tuple(argv),
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
    input_identifiers = tuple(args.input_identifier or ())
    if not input_identifiers:
        plan_identifier = str(
            plan.get("identifier") or "canonical-daily-operations-plan"
        )
        input_identifiers = (f"plan:{plan_identifier}",)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        default=os.getenv("CAPITAL_INTELLIGENCE_DAILY_OPERATION_PLAN"),
        help=(
            "Canonical stage plan JSON. Can also be provided by "
            "CAPITAL_INTELLIGENCE_DAILY_OPERATION_PLAN."
        ),
    )
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_DAILY_OPERATION_DATABASE",
            "database/canonical_daily_operations.db",
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
        detail="canonical daily operation claimed",
        observed_at=now,
    )
    runners, policies = _stage_configuration(plan)
    orchestrator = CanonicalDailyOperationsOrchestrator(
        store=SQLiteCanonicalDailyOperationsStore(args.database),
        runners=runners,
        retry_policies=policies,
    )
    result = orchestrator.run(request)
    print(json.dumps(operation_result_to_dict(result), indent=2, sort_keys=True))
    if result.status is DailyOperationStatus.COMPLETED:
        heartbeat.write(
            "healthy",
            cycle_key=request.idempotency_key,
            detail="canonical daily operation completed",
        )
        return 0
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.plan:
        parser.error(
            "--plan or CAPITAL_INTELLIGENCE_DAILY_OPERATION_PLAN is required"
        )
    if not 0 <= args.operation_hour <= 23:
        parser.error("--operation-hour must be between 0 and 23")
    if args.poll_seconds < 10:
        parser.error("--poll-seconds must be at least 10")
    try:
        plan = _load_plan(Path(args.plan).expanduser())
        settings = OperationalSettings.from_env()
        heartbeat = WorkerHeartbeatStore(settings.worker_heartbeat_path)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))

    if not args.loop:
        return _run_once(args, plan=plan, heartbeat=heartbeat)

    heartbeat.write("starting", detail="canonical daily operations loop started")
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
                detail=f"waiting for daily boundary {scheduled.isoformat()}",
            )
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
