"""Build normalized market snapshots from FRED economic data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from intelligence.models import MarketSnapshot
from intelligence.provider import load_sample_snapshot
from provider_configuration import (
    fred_credential_readiness,
    safe_provider_error,
)
from providers.fred import FREDProvider, FREDProviderError


@dataclass(frozen=True)
class EconomicReadings:
    """Raw economic readings displayed by the dashboard."""

    unemployment_rate: float
    inflation_rate: float
    ten_year_yield: float
    two_year_yield: float
    federal_funds_rate: float
    evaluated_at: datetime | None = None
    observation_dates: tuple[tuple[str, str], ...] = ()

    @property
    def yield_curve_spread(self) -> float:
        """Return the 10-year Treasury yield minus the 2-year yield."""

        return self.ten_year_yield - self.two_year_yield


@dataclass(frozen=True)
class EconomicDashboardData:
    """Complete economic data package for the application."""

    snapshot: MarketSnapshot
    readings: EconomicReadings | None
    data_source: str
    status: str


SERIES = {
    "unemployment": "UNRATE",
    "inflation": "CPIAUCSL",
    "ten_year": "DGS10",
    "two_year": "DGS2",
    "fed_funds": "FEDFUNDS",
}


def clamp(
    value: float,
    minimum: float = -1.0,
    maximum: float = 1.0,
) -> float:
    """Restrict a value to the normalized scoring range."""

    return max(minimum, min(maximum, value))


def build_live_snapshot(
    provider: FREDProvider | None = None,
) -> tuple[MarketSnapshot, EconomicReadings]:
    """Build normalized intelligence inputs from current FRED data."""

    fred = provider or FREDProvider()

    unemployment_observation = fred.get_latest_value(SERIES["unemployment"])
    unemployment = unemployment_observation.value

    inflation_observations = fred.get_observations(
        SERIES["inflation"],
        limit=14,
    )

    ten_year_observation = fred.get_latest_value(SERIES["ten_year"])
    ten_year = ten_year_observation.value

    two_year_observation = fred.get_latest_value(SERIES["two_year"])
    two_year = two_year_observation.value

    fed_funds_observation = fred.get_latest_value(SERIES["fed_funds"])
    fed_funds = fed_funds_observation.value

    latest_cpi = inflation_observations[0].value
    year_ago_cpi = inflation_observations[-1].value

    inflation_rate = (
        (latest_cpi / year_ago_cpi) - 1
    ) * 100

    yield_spread = ten_year - two_year

    growth_score = clamp(
        (5.0 - unemployment) / 3.0
    )

    inflation_score = clamp(
        (inflation_rate - 2.0) / 3.0
    )

    trend_score = clamp(
        yield_spread / 2.0
    )

    volatility_score = clamp(
        (fed_funds - 3.0) / 4.0
    )

    credit_score = clamp(
        -yield_spread / 2.0
    )

    snapshot = MarketSnapshot(
        growth=growth_score,
        inflation=inflation_score,
        trend=trend_score,
        volatility=volatility_score,
        credit=credit_score,
    )

    readings = EconomicReadings(
        unemployment_rate=unemployment,
        inflation_rate=inflation_rate,
        ten_year_yield=ten_year,
        two_year_yield=two_year,
        federal_funds_rate=fed_funds,
        evaluated_at=datetime.now(timezone.utc),
        observation_dates=(
            (SERIES["unemployment"], unemployment_observation.date),
            (SERIES["inflation"], inflation_observations[0].date),
            (SERIES["ten_year"], ten_year_observation.date),
            (SERIES["two_year"], two_year_observation.date),
            (SERIES["fed_funds"], fed_funds_observation.date),
        ),
    )

    return snapshot, readings


def load_dashboard_data() -> EconomicDashboardData:
    """Return live economic data or a truthfully labelled safe fallback."""

    readiness = fred_credential_readiness()
    if not readiness.configured:
        return EconomicDashboardData(
            snapshot=load_sample_snapshot(),
            readings=None,
            data_source="Sample data",
            status=readiness.detail,
        )

    provider = FREDProvider()

    try:
        snapshot, readings = build_live_snapshot(provider)

        return EconomicDashboardData(
            snapshot=snapshot,
            readings=readings,
            data_source="Live FRED data",
            status="Connected",
        )

    except FREDProviderError as error:
        return EconomicDashboardData(
            snapshot=load_sample_snapshot(),
            readings=None,
            data_source="Sample fallback",
            status=safe_provider_error("fred", error),
        )


def load_best_available_snapshot() -> tuple[MarketSnapshot, str]:
    """Return the best available snapshot for the CIO pipeline."""

    dashboard_data = load_dashboard_data()

    return (
        dashboard_data.snapshot,
        dashboard_data.data_source,
    )
