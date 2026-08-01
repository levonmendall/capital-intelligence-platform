"""Nonblocking provider snapshots for the Render Streamlit presentation thread.

The canonical CIO and background operating processes retain their normal synchronous,
fail-closed provider behavior.  These adapters are display-only: they prevent a slow
external provider from withholding the entire Streamlit page while a bounded daemon
refresh obtains the latest available snapshot.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Generic, TypeVar

from intelligence.provider import load_sample_snapshot
from live_operating_console import load_live_market_console as _load_live_market_console_sync
from providers.economic_snapshot import (
    EconomicDashboardData,
    load_dashboard_data as _load_dashboard_data_sync,
)


_LOGGER = logging.getLogger("capital_intelligence.render_data")
_T = TypeVar("_T")


class _BackgroundLoader(Generic[_T]):
    """Return a cached or truthful fallback while one daemon refresh runs."""

    def __init__(
        self,
        *,
        name: str,
        supplier: Callable[[], _T],
        fallback: Callable[[], _T],
        ttl_seconds: float,
        initial_wait_seconds: float = 0.75,
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

    def get(self) -> _T:
        now = time.monotonic()
        started_refresh = False
        with self._lock:
            if (
                self._value is not None
                and now - self._updated_at <= self._ttl_seconds
            ):
                return self._value

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
                started_refresh = True
            event = self._event

        # A stale, timestamped display snapshot is preferable to blocking the page.
        # Existing freshness controls continue to identify it as stale.
        if stale_value is not None:
            return stale_value

        if started_refresh and self._initial_wait_seconds > 0:
            event.wait(self._initial_wait_seconds)

        with self._lock:
            return self._value if self._value is not None else self._fallback()

    def _refresh(self, generation: int, event: threading.Event) -> None:
        value: _T | None = None
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

    def reset(self) -> None:
        """Clear cached display state for deterministic tests."""

        with self._lock:
            self._generation += 1
            self._value = None
            self._updated_at = 0.0
            self._refreshing = False
            self._event.set()
            self._event = threading.Event()


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


_LIVE_MARKET = _BackgroundLoader[dict[str, object]](
    name="live-market",
    supplier=lambda: _load_live_market_console_sync(),
    fallback=_live_market_fallback,
    ttl_seconds=20.0,
)
_ECONOMIC = _BackgroundLoader[EconomicDashboardData](
    name="economic-dashboard",
    supplier=lambda: _load_dashboard_data_sync(),
    fallback=_economic_fallback,
    ttl_seconds=120.0,
)


def load_live_market_console_nonblocking() -> dict[str, object]:
    """Return live market display data without blocking the Streamlit page."""

    return _LIVE_MARKET.get()


def load_dashboard_data_nonblocking() -> EconomicDashboardData:
    """Return economic display data without blocking the Streamlit page."""

    return _ECONOMIC.get()


def reset_nonblocking_render_data() -> None:
    """Reset both display caches for tests."""

    _LIVE_MARKET.reset()
    _ECONOMIC.reset()
