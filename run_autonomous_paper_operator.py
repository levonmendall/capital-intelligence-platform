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
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Sequence

from api.config import ApiSettings
from api.repositories import JournalRepository, RepositoryUnavailableError
from operations import OperationalSettings, WorkerHeartbeatStore, configure_logging
from paper_execution_runtime import attempt_paper_execution, paper_execution_mode
from portfolio.state import ensure_canonical_portfolio_store
from run_scheduler import build_worker


def _payloads(settings: ApiSettings) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    journal = JournalRepository(settings.journal_database, required=False)
    return (
        journal.latest_payload("portfolio_construction"),
        journal.latest_payload("daily_cio_briefing"),
    )


def _run_pass(*, settings: ApiSettings, worker) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    cycle = worker.run_due(now=now)
    deliveries = worker.dispatch_pending()
    try:
        construction, briefing = _payloads(settings)
    except RepositoryUnavailableError as error:
        construction, briefing = None, None
        journal_detail = str(error)
    else:
        journal_detail = None
    attempt = attempt_paper_execution(
        construction=construction,
        briefing=briefing,
        now=now,
    )
    return {
        "status": (
            "operating"
            if attempt.state in {"completed", "idle", "held", "paused"}
            else "degraded"
        ),
        "evaluated_at": now.isoformat(),
        "cycle": {
            "cycle_key": cycle.cycle_key,
            "status": cycle.status,
            "detail": cycle.detail,
            "snapshot_identifier": cycle.snapshot_identifier,
        },
        "delivery_count": len(deliveries),
        "journal_detail": journal_detail,
        "paper_execution": attempt.to_dict(),
        "execution_mode": paper_execution_mode().value,
        "fixture_stage_bindings_used": False,
        "launch_clearance_required": False,
        "manual_per_trade_approval_required": (
            paper_execution_mode().value == "manual"
        ),
        "paper_only": True,
        "real_money_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-seconds", type=int)
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
    heartbeat = WorkerHeartbeatStore(operational.worker_heartbeat_path)
    logger = logging.getLogger("capital_intelligence.paper_operator")

    try:
        ensure_canonical_portfolio_store(settings.portfolio_database)
        worker = build_worker(settings)
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
    while True:
        heartbeat.write("starting", detail="autonomous paper operator pass started")
        try:
            payload = _run_pass(settings=settings, worker=worker)
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
            heartbeat.write(
                "healthy" if payload["status"] == "operating" else "degraded",
                cycle_key=str(payload["cycle"]["cycle_key"]),
                detail=(
                    f"cio_cycle={payload['cycle']['status']}; "
                    f"paper_execution={state}; mode={payload['execution_mode']}"
                ),
            )
        print(json.dumps(payload, sort_keys=True))
        if run_once:
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
