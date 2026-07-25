"""Run scheduled daily Capital Intelligence cycles and selective delivery."""

from __future__ import annotations

import argparse
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
from intelligence.regime_pipeline import build_fred_regime_pipeline
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

    executor = CanonicalDailyCycleExecutor(
        daily_service,
        conviction_change_reader=conviction_change,
    )
    alert_path = settings.alert_database or settings.snapshot_database.with_name("alerts.db")
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
    alert_service = AlertDeliveryService(
        alert_store,
        dispatchers=dispatchers,
        maximum_attempts=settings.alert_maximum_attempts,
        base_retry_delay=timedelta(minutes=settings.alert_retry_minutes),
    )
    identity_store = SQLiteIdentityStore(
        settings.identity_database,
        access_ttl=timedelta(minutes=settings.access_token_minutes),
        refresh_ttl=timedelta(days=settings.refresh_token_days),
        password_minimum_length=settings.password_minimum_length,
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
    worker = build_worker(settings)
    if args.once:
        result = worker.run_due()
        worker.alert_service.dispatch_pending()
        print(
            f"cycle={result.cycle_key} status={result.status} "
            f"snapshot={result.snapshot_identifier or '-'}"
        )
        return 0 if result.status != "failed" else 1
    worker.serve_forever(
        poll_seconds=args.poll_seconds or settings.scheduler_poll_seconds
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
