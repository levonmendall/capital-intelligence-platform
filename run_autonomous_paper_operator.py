"""Operate the canonical CIO scheduler and paper executor without launch ceremony.

The operator is safe to start before a qualified opportunity exists. Missing or
insufficient investment evidence produces a truthful monitoring/idle state. It never
uses fixture stages, fabricates candidates, bypasses execution controls, or authorizes
real money.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from api.config import ApiSettings
from api.repositories import JournalRepository, RepositoryUnavailableError
from cio_pending_transactions import (
    paper_trading_launch_open,
    paper_trading_start_at,
    publish_pending_transaction_report,
)
from delivery.service import WorkerRunResult
from operations import (
    OperationalSettings,
    WorkerHeartbeatStore,
    component_heartbeat_path,
    configure_logging,
)
from operations.cio_reassessment import (
    AfterCloseLearningResult,
    ReassessmentResult,
    build_default_after_close_reviewer,
    build_default_reassessment_engine,
)
from paper_execution_runtime import (
    PaperExecutionAttempt,
    attempt_paper_execution,
    paper_execution_mode,
)
from portfolio.state import ensure_canonical_portfolio_store
from production_context_publication_runtime import prepare_production_context_for_cycle
from public_live_collection_runtime import collect_public_live_information_if_due
from run_scheduler import build_worker


_CONTEXT_CACHE_FILENAME = "production-context-publication-state.json"


def _payloads(settings: ApiSettings) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    journal = JournalRepository(settings.journal_database, required=False)
    return (
        journal.latest_payload("portfolio_construction"),
        journal.latest_payload("daily_cio_briefing"),
    )


def _invalidate_context_reuse_cache(settings: ApiSettings) -> None:
    """Remove only the latest-publication reuse pointer before a new intraday review.

    Persisted certified universes, screenings, contexts, portfolios, decisions, and
    journals remain untouched. This prevents a later slot or event from reusing the
    first review's evidence merely because both belong to the same market date.
    """

    path = settings.portfolio_database.parent / _CONTEXT_CACHE_FILENAME
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _attempt_due(worker, method_name: str, *args, **kwargs) -> bool:
    """Honor durable cooldowns while preserving lightweight test doubles."""

    method = getattr(worker, method_name, None)
    return True if not callable(method) else bool(method(*args, **kwargs))


def _blocked_cycle(context_publication) -> WorkerRunResult:
    return WorkerRunResult(
        cycle_key=context_publication.cycle_key,
        status="failed",
        detail=context_publication.detail,
    )


def _run_pass(
    *,
    settings: ApiSettings,
    worker,
    force_public_collection: bool = False,
    context_preparer=None,
    reassessment_engine=None,
    after_close_reviewer=None,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    public_collection = collect_public_live_information_if_due(
        now=now,
        force=force_public_collection,
    )

    reassessment = (
        reassessment_engine.scan_if_due(
            now=now,
            public_collection=public_collection,
        )
        if reassessment_engine is not None
        else ReassessmentResult(
            state="disabled",
            evaluated_at=now,
            detail="Material intraday reassessment is not configured.",
        )
    )

    scheduled_context = None
    scheduled_attempted = False
    if context_preparer is not None:
        scheduled_for = worker.scheduled_for(now)
        if (
            now >= scheduled_for
            and worker.needs_scheduled_cycle(now)
            and _attempt_due(worker, "scheduled_attempt_due", now)
        ):
            scheduled_attempted = True
            _invalidate_context_reuse_cache(settings)
            scheduled_context = context_preparer(
                settings=settings,
                scheduled_for=scheduled_for,
            )
            if scheduled_context.ready:
                cycle_now = datetime.now(timezone.utc)
                scheduled_cycle = worker.run_due(
                    now=cycle_now,
                    decision_as_of=scheduled_context.decision_as_of,
                )
            else:
                scheduled_cycle = _blocked_cycle(scheduled_context)
        else:
            scheduled_cycle = worker.run_due(now=now)
    else:
        scheduled_cycle = worker.run_due(now=now)

    if (
        scheduled_attempted
        and scheduled_cycle.status == "completed"
        and reassessment_engine is not None
    ):
        reassessment_engine.acknowledge_assessment(now=datetime.now(timezone.utc))

    event_context = None
    event_cycle = None
    if (
        reassessment.triggered
        and reassessment.trigger_key is not None
        and context_preparer is not None
        and worker.needs_triggered_cycle(reassessment.trigger_key, now=now)
        and _attempt_due(
            worker,
            "triggered_attempt_due",
            reassessment.trigger_key,
            now=now,
        )
    ):
        _invalidate_context_reuse_cache(settings)
        event_scheduled_for = datetime.now(timezone.utc)
        event_context = context_preparer(
            settings=settings,
            scheduled_for=event_scheduled_for,
        )
        if event_context.ready:
            event_now = datetime.now(timezone.utc)
            event_cycle = worker.run_triggered(
                reassessment.trigger_key,
                now=event_now,
                decision_as_of=event_context.decision_as_of,
            )
        else:
            event_cycle = _blocked_cycle(event_context)
        if event_cycle.status == "completed" and reassessment_engine is not None:
            reassessment_engine.acknowledge_assessment(now=datetime.now(timezone.utc))
        elif event_cycle.status == "failed" and reassessment_engine is not None:
            reassessment_engine.release_trigger(reassessment.trigger_key)

    after_close = (
        after_close_reviewer.run_if_due(now=datetime.now(timezone.utc))
        if after_close_reviewer is not None
        else AfterCloseLearningResult(
            state="disabled",
            evaluated_at=now,
            detail="After-close opportunity review is not configured.",
        )
    )

    cycle = event_cycle or scheduled_cycle
    context_publication = event_context or scheduled_context
    deliveries = worker.dispatch_pending()
    try:
        construction, briefing = _payloads(settings)
    except RepositoryUnavailableError as error:
        construction, briefing = None, None
        journal_detail = str(error)
    else:
        journal_detail = None

    execution_now = datetime.now(timezone.utc)
    mode = paper_execution_mode()
    launch_at = paper_trading_start_at()
    launch_open = paper_trading_launch_open(execution_now)
    publish_pending_transaction_report(
        construction=construction,
        briefing=briefing,
        generated_at=execution_now,
        execution_state="pending" if launch_open else "scheduled",
    )
    if launch_open:
        attempt = attempt_paper_execution(
            construction=construction,
            briefing=briefing,
            now=execution_now,
        )
    else:
        attempt = PaperExecutionAttempt(
            state="held",
            detail=(
                "Paper trading is scheduled to begin at "
                f"{launch_at.isoformat()}; the CIO report is available before launch."
            ),
            attempted_at=execution_now,
            mode=mode,
        )
    report = publish_pending_transaction_report(
        construction=construction,
        briefing=briefing,
        generated_at=execution_now,
        execution_state=attempt.state,
    )
    operating_attempt = attempt.state in {"completed", "idle", "held", "paused"}
    context_ready = context_publication is None or context_publication.ready
    monitoring_ready = reassessment.state != "failed"
    learning_ready = after_close.state != "failed"
    return {
        "status": (
            "operating"
            if (
                operating_attempt
                and public_collection.state != "failed"
                and context_ready
                and monitoring_ready
                and learning_ready
            )
            else "degraded"
        ),
        "evaluated_at": execution_now.isoformat(),
        "public_live_information": public_collection.to_dict(),
        "material_reassessment": reassessment.to_dict(),
        "after_close_learning": after_close.to_dict(),
        "production_context_publication": (
            None if context_publication is None else context_publication.to_dict()
        ),
        "scheduled_cycle": {
            "cycle_key": scheduled_cycle.cycle_key,
            "status": scheduled_cycle.status,
            "detail": scheduled_cycle.detail,
            "snapshot_identifier": scheduled_cycle.snapshot_identifier,
        },
        "event_cycle": (
            None
            if event_cycle is None
            else {
                "cycle_key": event_cycle.cycle_key,
                "status": event_cycle.status,
                "detail": event_cycle.detail,
                "snapshot_identifier": event_cycle.snapshot_identifier,
            }
        ),
        "cycle": {
            "cycle_key": cycle.cycle_key,
            "status": cycle.status,
            "detail": cycle.detail,
            "snapshot_identifier": cycle.snapshot_identifier,
        },
        "delivery_count": len(deliveries),
        "journal_detail": journal_detail,
        "paper_execution": attempt.to_dict(),
        "execution_mode": mode.value,
        "paper_trading_start_at": launch_at.isoformat(),
        "paper_trading_launch_open": launch_open,
        "pending_transaction_report": {
            "report_state": report["report_state"],
            "transaction_count": report["transaction_count"],
            "summary": report["summary"],
            "json_path": report["json_path"],
            "markdown_path": report["markdown_path"],
        },
        "fixture_stage_bindings_used": False,
        "launch_clearance_required": False,
        "manual_per_trade_approval_required": mode.value == "manual",
        "paper_only": True,
        "real_money_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-seconds", type=int)
    parser.add_argument(
        "--force-public-collection",
        action="store_true",
        help=(
            "Collect public live information on the first operator pass even when "
            "the persisted hourly window has not elapsed."
        ),
    )
    args = parser.parse_args(argv)
    if args.once and args.loop:
        parser.error("--once and --loop are mutually exclusive")

    settings = ApiSettings.from_env()
    operational = OperationalSettings.from_env()
    if operational.service_name == "capital-intelligence-api":
        operational = replace(
            operational,
            service_name="capital-intelligence-paper-operator",
        )
    configure_logging(operational)
    heartbeat = WorkerHeartbeatStore(
        component_heartbeat_path(
            Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")),
            "cio-paper-operator",
        )
    )
    logger = logging.getLogger("capital_intelligence.paper_operator")

    try:
        ensure_canonical_portfolio_store(settings.portfolio_database)
        worker = build_worker(settings)
        reassessment_engine = build_default_reassessment_engine(settings)
        after_close_reviewer = build_default_after_close_reviewer(settings)
    except (ImportError, AttributeError, OSError, TypeError, ValueError, RuntimeError) as error:
        heartbeat.write("failed", detail=str(error)[:1000])
        logger.exception("paper operator configuration failed")
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(error),
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 2

    poll_seconds = args.poll_seconds or settings.scheduler_poll_seconds
    if poll_seconds < 5:
        parser.error("--poll-seconds must be at least 5")

    run_once = args.once or not args.loop
    force_public_collection = args.force_public_collection
    while True:
        heartbeat.write("starting", detail="autonomous paper operator pass started")
        try:
            payload = _run_pass(
                settings=settings,
                worker=worker,
                force_public_collection=force_public_collection,
                context_preparer=prepare_production_context_for_cycle,
                reassessment_engine=reassessment_engine,
                after_close_reviewer=after_close_reviewer,
            )
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            heartbeat.write("degraded", detail=str(error)[:1000])
            logger.exception("paper operator pass failed closed")
            payload = {
                "status": "degraded",
                "error": str(error),
                "paper_only": True,
                "real_money_authorized": False,
            }
        else:
            state = str(payload["paper_execution"]["state"])
            public_state = str(payload["public_live_information"]["state"])
            reassessment_state = str(payload["material_reassessment"]["state"])
            learning_state = str(payload["after_close_learning"]["state"])
            context_payload = payload.get("production_context_publication")
            context_state = (
                "not_due"
                if context_payload is None
                else str(context_payload["state"])
            )
            heartbeat.write(
                "healthy" if payload["status"] == "operating" else "degraded",
                cycle_key=str(payload["cycle"]["cycle_key"]),
                detail=(
                    f"public_collection={public_state}; "
                    f"reassessment={reassessment_state}; "
                    f"after_close_learning={learning_state}; "
                    f"production_context={context_state}; "
                    f"cio_cycle={payload['cycle']['status']}; "
                    f"paper_execution={state}; mode={payload['execution_mode']}"
                ),
            )
        print(json.dumps(payload, sort_keys=True))
        force_public_collection = False
        if run_once:
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
