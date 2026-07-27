"""Run the scheduled canonical CIO cycle and drain canonical delivery."""

from __future__ import annotations

import argparse
import importlib
import logging
import time
from dataclasses import replace
from datetime import timedelta

from api.config import ApiSettings
from application import ProductionCanonicalCIOExecutor
from application.cio_cycle import CanonicalCIOCycle
from cio.persistence import SQLiteCIOJournal
from delivery import (
    AlertChannel,
    AlertDeliveryService,
    SMTPEmailDispatcher,
    SQLiteAlertStore,
    ScheduledCanonicalCIOWorker,
)
from operations import OperationalSettings, WorkerHeartbeatStore, configure_logging
from screening import SQLiteFullUniverseScreeningStore
from security import SQLiteIdentityStore


def _context_provider(specification: str | None):
    if specification is None:
        raise RuntimeError(
            "CAPITAL_INTELLIGENCE_CANONICAL_CONTEXT_PROVIDER is required; "
            "there is no legacy scheduler fallback"
        )
    module_name, attribute_name = specification.split(":", 1)
    factory = getattr(importlib.import_module(module_name), attribute_name, None)
    if not callable(factory):
        raise ValueError(
            f"canonical context-provider factory {specification!r} is not callable"
        )
    return factory()


def build_worker(settings: ApiSettings) -> ScheduledCanonicalCIOWorker:
    """Build the only active scheduled investment-decision authority."""

    journal = SQLiteCIOJournal(settings.journal_database)
    journal.verify_integrity()
    screening_store = SQLiteFullUniverseScreeningStore(
        settings.full_universe_screening_database
    )
    screening_store.verify_integrity()
    provider = _context_provider(settings.canonical_cycle_context_provider)
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(journal=journal),
        screening_store=screening_store,
        context_provider=provider,
    )
    alert_path = (
        settings.alert_database
        or settings.snapshot_database.with_name("alerts.db")
    )
    alert_store = SQLiteAlertStore(alert_path)
    dispatchers = {}
    if settings.smtp_host and settings.smtp_from_address:
        dispatchers[AlertChannel.EMAIL] = SMTPEmailDispatcher(
            host=settings.smtp_host,
            port=settings.smtp_port,
            from_address=settings.smtp_from_address,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
        )
    identity_store = SQLiteIdentityStore(settings.identity_database)
    alert_service = AlertDeliveryService(
        alert_store,
        dispatchers=dispatchers,
        maximum_attempts=settings.alert_maximum_attempts,
        base_retry_delay=timedelta(minutes=settings.alert_retry_minutes),
    )
    return ScheduledCanonicalCIOWorker(
        executor,
        alert_store,
        delivery_service=alert_service,
        identity_store=identity_store,
        schedule_timezone=settings.scheduler_timezone,
        schedule_hour=settings.scheduler_hour,
        cycle_retry_delay=timedelta(minutes=settings.scheduler_retry_minutes),
        cycle_lease=timedelta(minutes=settings.scheduler_lease_minutes),
    )


def _run_pass(worker: ScheduledCanonicalCIOWorker, heartbeat: WorkerHeartbeatStore) -> int:
    heartbeat.write("starting", detail="canonical CIO cycle pass started")
    try:
        result = worker.run_due()
        deliveries = worker.dispatch_pending()
    except Exception as error:
        heartbeat.write("failed", detail=str(error)[:1000])
        logging.getLogger("capital_intelligence.scheduler").exception(
            "canonical scheduler pass failed"
        )
        return 1
    status = "degraded" if result.status == "failed" else "healthy"
    heartbeat.write(
        status,
        cycle_key=result.cycle_key,
        detail=(
            f"cycle_status={result.status}; "
            f"deliveries_processed={len(deliveries)}; "
            f"briefing={result.snapshot_identifier or '-'}"
        ),
    )
    logging.getLogger("capital_intelligence.scheduler").info(
        "canonical scheduler pass completed",
        extra={
            "cycle_key": result.cycle_key,
            "cycle_status": result.status,
            "briefing_identifier": result.snapshot_identifier,
            "deliveries_processed": len(deliveries),
        },
    )
    return 0 if result.status != "failed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the canonical CIO production scheduler and delivery worker."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one due canonical-cycle and delivery pass, then exit.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=None,
        help="Override the configured worker poll interval.",
    )
    args = parser.parse_args()
    settings = ApiSettings.from_env()
    operational = OperationalSettings.from_env()
    if operational.service_name == "capital-intelligence-api":
        operational = replace(
            operational,
            service_name="capital-intelligence-scheduler",
        )
    configure_logging(operational)
    heartbeat = WorkerHeartbeatStore(operational.worker_heartbeat_path)
    try:
        worker = build_worker(settings)
    except (ImportError, AttributeError, OSError, TypeError, ValueError, RuntimeError) as error:
        heartbeat.write("failed", detail=str(error)[:1000])
        logging.getLogger("capital_intelligence.scheduler").exception(
            "canonical scheduler configuration failed"
        )
        return 2
    if args.once:
        return _run_pass(worker, heartbeat)
    poll_seconds = args.poll_seconds or settings.scheduler_poll_seconds
    if poll_seconds < 1:
        parser.error("poll interval must be positive")
    while True:
        _run_pass(worker, heartbeat)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
