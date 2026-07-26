"""Run scheduled daily Capital Intelligence cycles and selective delivery."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import replace
from datetime import timedelta

from api.config import ApiSettings
from application import DailyCapitalIntelligenceService, SQLiteDailySnapshotStore
from delivery import (
    AlertChannel,
    AlertDeliveryService,
    CanonicalDailyCycleExecutor,
    SMTPEmailDispatcher,
    SQLiteAlertStore,
    ScheduledDailyIntelligenceWorker,
)
from intelligence.business_cycle import build_fred_business_cycle_engine
from intelligence.credit_cycle import build_fred_credit_cycle_engine
from intelligence.engine_cycle import AnalyticalEngineCycleExecutor
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import build_fred_global_liquidity_engine
from intelligence.market_breadth import build_configured_market_breadth_engine
from intelligence.regime_pipeline import build_fred_regime_pipeline
from intelligence.technical_momentum import (
    build_configured_technical_momentum_engine,
)
from intelligence.valuation import build_configured_valuation_engine
from operations import OperationalSettings, WorkerHeartbeatStore, configure_logging
from personal_cio import PersonalCIOAlertPlanner
from reporting import build_conviction_trend_from_store
from security import SQLiteIdentityStore


def build_worker(settings: ApiSettings) -> ScheduledDailyIntelligenceWorker:
    snapshot_store = SQLiteDailySnapshotStore(settings.snapshot_database)
    daily_service = DailyCapitalIntelligenceService(
        build_fred_regime_pipeline(),
        store=snapshot_store,
    )

    def conviction_change() -> int | None:
        trend = build_conviction_trend_from_store(
            snapshot_store.path,
            lookback=settings.conviction_default_lookback,
        )
        return trend.change_points

    canonical_executor = CanonicalDailyCycleExecutor(
        daily_service,
        conviction_change_reader=conviction_change,
    )
    analytical_store = SQLiteAnalyticalEngineStore(
        settings.snapshot_database.with_name("analytical_engines.db")
    )
    executor = AnalyticalEngineCycleExecutor(
        canonical_executor,
        (
            build_fred_global_liquidity_engine(),
            build_fred_business_cycle_engine(),
            build_fred_credit_cycle_engine(),
            build_configured_market_breadth_engine(),
            build_configured_valuation_engine(),
            build_configured_technical_momentum_engine(),
        ),
        analytical_store,
    )
    alert_path = (
        settings.alert_database
        or settings.snapshot_database.with_name("alerts.db")
    )
    alert_store = SQLiteAlertStore(alert_path)
    identity_store = SQLiteIdentityStore(
        settings.identity_database,
        access_ttl=timedelta(minutes=settings.access_token_minutes),
        refresh_ttl=timedelta(days=settings.refresh_token_days),
        password_minimum_length=settings.password_minimum_length,
    )
    planner = PersonalCIOAlertPlanner(
        identity_store=identity_store,
        snapshot_database=settings.snapshot_database,
        portfolio_database=settings.portfolio_database,
        policy_database=settings.investor_memory_database.with_name(
            "investment_policy.db"
        ),
    )
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
    alert_service = AlertDeliveryService(
        alert_store,
        planner=planner,
        dispatchers=dispatchers,
        maximum_attempts=settings.alert_maximum_attempts,
        base_retry_delay=timedelta(minutes=settings.alert_retry_minutes),
    )
    return ScheduledDailyIntelligenceWorker(
        executor,
        identity_store,
        alert_service,
        schedule_timezone=settings.scheduler_timezone,
        schedule_hour=settings.scheduler_hour,
        cycle_retry_delay=timedelta(minutes=settings.scheduler_retry_minutes),
        cycle_lease=timedelta(minutes=settings.scheduler_lease_minutes),
    )


def _run_pass(worker, heartbeat: WorkerHeartbeatStore) -> int:
    heartbeat.write("starting", detail="scheduled cycle pass started")
    try:
        result = worker.run_due()
        deliveries = worker.alert_service.dispatch_pending()
    except Exception as error:
        heartbeat.write("failed", detail=str(error)[:1000])
        logging.getLogger("capital_intelligence.scheduler").exception(
            "scheduler pass failed"
        )
        return 1
    status = "degraded" if result.status == "failed" else "healthy"
    heartbeat.write(
        status,
        cycle_key=result.cycle_key,
        detail=(
            f"cycle_status={result.status}; "
            f"deliveries_processed={len(deliveries)}; "
            f"snapshot={result.snapshot_identifier or '-'}"
        ),
    )
    logging.getLogger("capital_intelligence.scheduler").info(
        "scheduler pass completed",
        extra={
            "cycle_key": result.cycle_key,
            "cycle_status": result.status,
            "snapshot_identifier": result.snapshot_identifier,
            "deliveries_processed": len(deliveries),
        },
    )
    return 0 if result.status != "failed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Capital Intelligence daily scheduler and alert worker."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one due-cycle and delivery pass, then exit.",
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
    worker = build_worker(settings)
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
