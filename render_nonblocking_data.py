"""Nonblocking display snapshots for the Render Streamlit presentation thread.

The canonical CIO, validation, portfolio, screening, and paper-execution processes
retain their synchronous fail-closed behavior.  This module is display-only.  It
prevents provider latency, SQLite writer contention, full-chain verification, or
large append-only artifacts from withholding an entire Streamlit page.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Generic, Hashable, Mapping, TypeVar

import educational_market_briefing_ui as event_ui
from api.config import ApiSettings
from api.repositories import DailySnapshotRepository, JournalRepository
from core.portfolio import (
    get_mandate_details as _get_mandate_details_sync,
    get_portfolio_totals as _get_portfolio_totals_sync,
    get_trade_history as _get_trade_history_sync,
)
from intelligence.provider import load_sample_snapshot
from live_operating_console import load_live_market_console as _load_live_market_console_sync
from operating_intelligence_ui import (
    DecisionAccountabilitySnapshot,
    OpportunityScanSnapshot,
    load_decision_accountability as _load_decision_accountability_sync,
    load_opportunity_scan as _load_opportunity_scan_sync,
)
from operating_status import (
    CIOOperatingStatus,
    load_cio_operating_status as _load_cio_operating_status_sync,
)
from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from providers.economic_snapshot import (
    EconomicDashboardData,
    load_dashboard_data as _load_dashboard_data_sync,
)


_LOGGER = logging.getLogger("capital_intelligence.render_data")
_T = TypeVar("_T")
_K = TypeVar("_K", bound=Hashable)


def _unwrapped(function: Callable[..., _T]) -> Callable[..., _T]:
    return getattr(function, "__wrapped__", function)


class _BackgroundLoader(Generic[_T]):
    """Return a cached or truthful fallback while one daemon refresh runs."""

    def __init__(
        self,
        *,
        name: str,
        supplier: Callable[[], _T],
        fallback: Callable[[], _T],
        ttl_seconds: float,
        initial_wait_seconds: float = 0.05,
    ) -> None:
        self._name = name
        self._supplier = supplier
        self._fallback = fallback
        self._ttl_seconds = float(ttl_seconds)
        self._initial_wait_seconds = float(initial_wait_seconds)
        self._lock = threading.Lock()
        self._value: _T | None = None
        self._updated_at = 0.0
        self._refreshing = False
        self._event = threading.Event()
        self._generation = 0

    def _begin_refresh(self) -> tuple[_T | None, threading.Event, bool]:
        now = time.monotonic()
        with self._lock:
            if (
                self._value is not None
                and now - self._updated_at <= self._ttl_seconds
            ):
                return self._value, self._event, False
            stale_value = self._value
            if not self._refreshing:
                self._refreshing = True
                self._event = threading.Event()
                self._generation += 1
                generation = self._generation
                thread = threading.Thread(
                    target=self._refresh,
                    args=(generation, self._event),
                    name=f"render-{self._name}-refresh",
                    daemon=True,
                )
                thread.start()
                return stale_value, self._event, True
            return stale_value, self._event, False

    def get(self) -> _T:
        stale_value, event, started_refresh = self._begin_refresh()
        if stale_value is not None:
            return stale_value
        if started_refresh and self._initial_wait_seconds > 0:
            event.wait(self._initial_wait_seconds)
        with self._lock:
            return self._value if self._value is not None else self._fallback()

    def prewarm(self) -> None:
        """Start a refresh without making the caller wait."""

        self._begin_refresh()

    def _refresh(self, generation: int, event: threading.Event) -> None:
        value: _T | None = None
        started_at = time.monotonic()
        try:
            value = self._supplier()
        except Exception as error:  # The display layer must never take down the app.
            _LOGGER.warning(
                "Render background data refresh failed: source=%s error_class=%s",
                self._name,
                type(error).__name__,
            )
        finally:
            with self._lock:
                if generation == self._generation:
                    if value is not None:
                        self._value = value
                        self._updated_at = time.monotonic()
                    self._refreshing = False
                event.set()
            _LOGGER.info(
                "Render background data refresh completed: source=%s duration_seconds=%.3f",
                self._name,
                time.monotonic() - started_at,
            )

    def reset(self) -> None:
        """Clear cached display state for deterministic tests."""

        with self._lock:
            self._generation += 1
            self._value = None
            self._updated_at = 0.0
            self._refreshing = False
            self._event.set()
            self._event = threading.Event()


class _KeyedBackgroundLoader(Generic[_K, _T]):
    """Create one bounded background cache per immutable lookup key."""

    def __init__(
        self,
        *,
        name: str,
        supplier: Callable[[_K], _T],
        fallback: Callable[[_K], _T],
        ttl_seconds: float,
        initial_wait_seconds: float = 0.05,
    ) -> None:
        self._name = name
        self._supplier = supplier
        self._fallback = fallback
        self._ttl_seconds = ttl_seconds
        self._initial_wait_seconds = initial_wait_seconds
        self._lock = threading.Lock()
        self._loaders: dict[_K, _BackgroundLoader[_T]] = {}

    def _loader(self, key: _K) -> _BackgroundLoader[_T]:
        with self._lock:
            loader = self._loaders.get(key)
            if loader is None:
                loader = _BackgroundLoader(
                    name=f"{self._name}-{str(key)[:80]}",
                    supplier=lambda key=key: self._supplier(key),
                    fallback=lambda key=key: self._fallback(key),
                    ttl_seconds=self._ttl_seconds,
                    initial_wait_seconds=self._initial_wait_seconds,
                )
                self._loaders[key] = loader
            return loader

    def get(self, key: _K) -> _T:
        return self._loader(key).get()

    def prewarm(self, key: _K) -> None:
        self._loader(key).prewarm()

    def reset(self) -> None:
        with self._lock:
            loaders = tuple(self._loaders.values())
            self._loaders.clear()
        for loader in loaders:
            loader.reset()


def _live_market_supplier() -> dict[str, object]:
    return dict(_unwrapped(_load_live_market_console_sync)())


def _live_market_fallback() -> dict[str, object]:
    evaluated_at = datetime.now(timezone.utc)
    return {
        "status": "unavailable",
        "detail": (
            "Live Alpaca/IEX display data is refreshing in the background. "
            "The canonical portfolio and governed records remain authoritative."
        ),
        "configuration_state": "background_refresh_pending",
        "evaluated_at": evaluated_at.isoformat(),
        "account_status": "Refreshing",
        "market_open": None,
        "clock_at": None,
        "quote_count": 0,
        "expected_quote_count": 15,
        "latest_quote_at": None,
        "rows": [],
        "source": "Alpaca paper account + IEX",
        "paper_only": True,
        "real_money_authorized": False,
    }


def _economic_fallback() -> EconomicDashboardData:
    return EconomicDashboardData(
        snapshot=load_sample_snapshot(),
        readings=None,
        data_source="Background refresh pending",
        status=(
            "Live FRED display data is refreshing in the background. No sample "
            "reading is presented as current economic evidence."
        ),
    )


def _public_event_supplier() -> event_ui.PublicEventSnapshot:
    path = event_ui._records_path()
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    reader = _unwrapped(event_ui._read_public_event_file)
    snapshot = reader(str(path), modified_ns)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    timed_records: list[tuple[datetime, Mapping[str, object]]] = []
    for record in snapshot.records:
        observed_at = None
        for field_name in ("available_at", "published_at", "event_at"):
            observed_at = event_ui._parse_datetime(record.get(field_name))
            if observed_at is not None:
                break
        if observed_at is not None and observed_at >= cutoff:
            timed_records.append((observed_at, record))
    timed_records.sort(key=lambda item: item[0], reverse=True)
    return event_ui.PublicEventSnapshot(
        records=tuple(record for _, record in timed_records[:1000]),
        evaluated_at=snapshot.evaluated_at,
        state=snapshot.state,
        detail=snapshot.detail,
    )


def _public_event_fallback() -> event_ui.PublicEventSnapshot:
    return event_ui.PublicEventSnapshot(
        records=(),
        evaluated_at=None,
        state="refreshing",
        detail=(
            "Governed public-event metadata is refreshing in the background. "
            "No event is represented as current until the refresh completes."
        ),
    )


def _settings() -> ApiSettings:
    return ApiSettings.from_env()


def _journal_latest_supplier(event_type: str) -> dict[str, object] | None:
    settings = _settings()
    return JournalRepository(
        settings.journal_database,
        required=settings.require_journal,
    ).latest_payload(event_type)


def _journal_history_supplier(key: tuple[str, int]) -> tuple[dict[str, object], ...]:
    event_type, limit = key
    settings = _settings()
    return tuple(
        JournalRepository(
            settings.journal_database,
            required=settings.require_journal,
        ).history(event_type, limit=limit)
    )


def _latest_theses_supplier() -> tuple[dict[str, object], ...]:
    settings = _settings()
    return tuple(
        JournalRepository(
            settings.journal_database,
            required=settings.require_journal,
        ).latest_per_aggregate("thesis_snapshot", limit=200)
    )


def _diagnostic_supplier() -> dict[str, object] | None:
    return DailySnapshotRepository(_settings().snapshot_database).latest_payload()


def _portfolio_totals_supplier() -> dict[str, object]:
    payload = dict(_get_portfolio_totals_sync())
    payload["_available"] = True
    return payload


def _portfolio_totals_fallback() -> dict[str, object]:
    return {
        "_available": False,
        "detail": "Canonical portfolio display data is refreshing in the background.",
        "mandate_count": 0,
        "portfolio_count": 0,
        "starting_capital": 0.0,
        "starting": 0.0,
        "cash": 0.0,
        "nav": 0.0,
        "total_return": 0.0,
        "total_pnl": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "cash_fx_pnl": 0.0,
        "non_trade_pnl": 0.0,
        "net_external_flows": 0.0,
        "fees_paid": 0.0,
        "accounting_residual": 0.0,
        "period_pnl": 0.0,
        "day_pnl": 0.0,
        "day_return": 0.0,
        "as_of": None,
    }


def _mandate_supplier(code: str) -> dict[str, object] | None:
    value = _get_mandate_details_sync(code)
    if value is None:
        return None
    payload = dict(value)
    payload["_available"] = True
    return payload


def _trade_history_supplier(key: tuple[str | None, int]) -> list[dict[str, object]]:
    code, limit = key
    return list(_get_trade_history_sync(code, limit=limit))


def _operating_status_fallback() -> CIOOperatingStatus:
    release = (
        os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
        or os.getenv("RENDER_GIT_COMMIT")
        or "unknown"
    ).strip()
    return CIOOperatingStatus(
        state="refreshing",
        label="CIO status refreshing",
        headline="Operating status is refreshing",
        detail=(
            "The display is waiting for a bounded background read of the operating "
            "stores. The CIO worker remains independently authoritative."
        ),
        observed_at=datetime.now(timezone.utc),
        release=release,
    )


def _opportunity_fallback() -> OpportunityScanSnapshot:
    return OpportunityScanSnapshot(
        state="refreshing",
        as_of=None,
        broad_assets_screened=None,
        snapshot_covered=None,
        companies_deepened=None,
        governed_candidates=None,
        opportunities_reaching_cio=None,
        strongest_alternative="Refreshing",
        strongest_stage="Background read in progress",
        main_reason="The latest governed opportunity scan is being loaded.",
        decision_reference="Unavailable",
        detail="No scan count is represented as current until the refresh completes.",
    )


def _accountability_fallback() -> DecisionAccountabilitySnapshot:
    return DecisionAccountabilitySnapshot(
        state="refreshing",
        recorded_decisions=0,
        awaiting_evaluation=0,
        avoided_losses=0,
        missed_opportunities=0,
        supported_gains=0,
        supported_losses=0,
        neutral_outcomes=0,
        lesson="Decision-accountability evidence is refreshing in the background.",
        recent_outcomes=(),
        detail="No outcome count is represented as current until the refresh completes.",
    )


_LIVE_MARKET = _BackgroundLoader[dict[str, object]](
    name="live-market",
    supplier=_live_market_supplier,
    fallback=_live_market_fallback,
    ttl_seconds=20.0,
)
_ECONOMIC = _BackgroundLoader[EconomicDashboardData](
    name="economic-dashboard",
    supplier=_load_dashboard_data_sync,
    fallback=_economic_fallback,
    ttl_seconds=120.0,
)
_PUBLIC_EVENTS = _BackgroundLoader[event_ui.PublicEventSnapshot](
    name="public-events",
    supplier=_public_event_supplier,
    fallback=_public_event_fallback,
    ttl_seconds=120.0,
)
_JOURNAL_LATEST = _KeyedBackgroundLoader[str, dict[str, object] | None](
    name="journal-latest",
    supplier=_journal_latest_supplier,
    fallback=lambda _key: None,
    ttl_seconds=15.0,
)
_JOURNAL_HISTORY = _KeyedBackgroundLoader[
    tuple[str, int], tuple[dict[str, object], ...]
](
    name="journal-history",
    supplier=_journal_history_supplier,
    fallback=lambda _key: (),
    ttl_seconds=30.0,
)
_LATEST_THESES = _BackgroundLoader[tuple[dict[str, object], ...]](
    name="latest-theses",
    supplier=_latest_theses_supplier,
    fallback=lambda: (),
    ttl_seconds=30.0,
)
_DIAGNOSTIC = _BackgroundLoader[dict[str, object] | None](
    name="diagnostic-snapshot",
    supplier=_diagnostic_supplier,
    fallback=lambda: None,
    ttl_seconds=30.0,
)
_PORTFOLIO_TOTALS = _BackgroundLoader[dict[str, object]](
    name="portfolio-totals",
    supplier=_portfolio_totals_supplier,
    fallback=_portfolio_totals_fallback,
    ttl_seconds=15.0,
)
_MANDATE = _KeyedBackgroundLoader[str, dict[str, object] | None](
    name="portfolio-mandate",
    supplier=_mandate_supplier,
    fallback=lambda _key: None,
    ttl_seconds=15.0,
)
_TRADE_HISTORY = _KeyedBackgroundLoader[
    tuple[str | None, int], list[dict[str, object]]
](
    name="trade-history",
    supplier=_trade_history_supplier,
    fallback=lambda _key: [],
    ttl_seconds=30.0,
)
_OPERATING_STATUS = _BackgroundLoader[CIOOperatingStatus](
    name="operating-status",
    supplier=_load_cio_operating_status_sync,
    fallback=_operating_status_fallback,
    ttl_seconds=15.0,
)
_OPPORTUNITY = _BackgroundLoader[OpportunityScanSnapshot](
    name="opportunity-scan",
    supplier=_load_opportunity_scan_sync,
    fallback=_opportunity_fallback,
    ttl_seconds=60.0,
)
_ACCOUNTABILITY = _BackgroundLoader[DecisionAccountabilitySnapshot](
    name="decision-accountability",
    supplier=_load_decision_accountability_sync,
    fallback=_accountability_fallback,
    ttl_seconds=60.0,
)


def load_live_market_console_nonblocking() -> dict[str, object]:
    return _LIVE_MARKET.get()


def load_dashboard_data_nonblocking() -> EconomicDashboardData:
    return _ECONOMIC.get()


def load_public_event_snapshot_nonblocking() -> event_ui.PublicEventSnapshot:
    return _PUBLIC_EVENTS.get()


def load_journal_latest_nonblocking(event_type: str) -> dict[str, object] | None:
    return _JOURNAL_LATEST.get(str(event_type))


def load_journal_history_nonblocking(
    event_type: str,
    *,
    limit: int = 50,
) -> tuple[dict[str, object], ...]:
    return _JOURNAL_HISTORY.get((str(event_type), int(limit)))


def load_latest_theses_nonblocking() -> tuple[dict[str, object], ...]:
    return _LATEST_THESES.get()


def load_diagnostic_environment_nonblocking() -> dict[str, object] | None:
    return _DIAGNOSTIC.get()


def get_portfolio_totals_nonblocking() -> dict[str, object]:
    return _PORTFOLIO_TOTALS.get()


def get_mandate_details_nonblocking(
    mandate_code: str = CANONICAL_PORTFOLIO_CODE,
) -> dict[str, object] | None:
    return _MANDATE.get(str(mandate_code).strip().upper())


def get_trade_history_nonblocking(
    mandate_code: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    normalized = None if mandate_code is None else str(mandate_code).strip().upper()
    return _TRADE_HISTORY.get((normalized, int(limit)))


def load_cio_operating_status_nonblocking(
    *,
    now: datetime | None = None,
) -> CIOOperatingStatus:
    # The presentation snapshot owns its own observed timestamp. A caller-provided
    # clock is retained only by the synchronous canonical status implementation.
    del now
    return _OPERATING_STATUS.get()


def load_opportunity_scan_nonblocking() -> OpportunityScanSnapshot:
    return _OPPORTUNITY.get()


def load_decision_accountability_nonblocking() -> DecisionAccountabilitySnapshot:
    return _ACCOUNTABILITY.get()


def prewarm_render_data() -> None:
    """Start the common display reads before the first surface requests them."""

    _LIVE_MARKET.prewarm()
    _ECONOMIC.prewarm()
    _PUBLIC_EVENTS.prewarm()
    _JOURNAL_LATEST.prewarm("daily_cio_briefing")
    _JOURNAL_LATEST.prewarm("portfolio_construction")
    _DIAGNOSTIC.prewarm()
    _PORTFOLIO_TOTALS.prewarm()
    _MANDATE.prewarm(CANONICAL_PORTFOLIO_CODE)
    _OPERATING_STATUS.prewarm()
    _OPPORTUNITY.prewarm()
    _ACCOUNTABILITY.prewarm()


def reset_nonblocking_render_data() -> None:
    """Reset all display caches for deterministic tests."""

    for loader in (
        _LIVE_MARKET,
        _ECONOMIC,
        _PUBLIC_EVENTS,
        _JOURNAL_LATEST,
        _JOURNAL_HISTORY,
        _LATEST_THESES,
        _DIAGNOSTIC,
        _PORTFOLIO_TOTALS,
        _MANDATE,
        _TRADE_HISTORY,
        _OPERATING_STATUS,
        _OPPORTUNITY,
        _ACCOUNTABILITY,
    ):
        loader.reset()
