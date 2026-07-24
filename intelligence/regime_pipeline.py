"""Canonical point-in-time economic-regime application service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType

from data import (
    NormalizedObservation,
    ObservationProvider,
    ObservationQuery,
    ProviderError,
    SeriesSpecification,
)
from economic_regime import (
    EvidenceBasedRegimeResult,
    RegimeEvidenceBuilder,
)
from providers.fred import FREDProvider
from providers.fred_series import FRED_SERIES


class SeriesLoadState(str, Enum):
    """Outcome of retrieving one required regime series."""

    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class RegimeSeriesRequest:
    """One provider-neutral series request used by the pipeline."""

    signal: str
    series: SeriesSpecification
    limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.signal, str):
            raise TypeError("signal must be a string")
        normalized = self.signal.strip()
        if not normalized:
            raise ValueError("signal cannot be empty")
        if not isinstance(self.series, SeriesSpecification):
            raise TypeError(
                "series must be a SeriesSpecification"
            )
        if isinstance(self.limit, bool) or not isinstance(
            self.limit,
            int,
        ):
            raise TypeError("limit must be an int")
        if not 1 <= self.limit <= 100_000:
            raise ValueError(
                "limit must be between 1 and 100000"
            )
        object.__setattr__(self, "signal", normalized)


@dataclass(frozen=True, slots=True)
class RegimeSeriesLoad:
    """Auditable retrieval outcome for one requested series."""

    request: RegimeSeriesRequest
    state: SeriesLoadState
    observations: tuple[NormalizedObservation, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, RegimeSeriesRequest):
            raise TypeError(
                "request must be a RegimeSeriesRequest"
            )
        if not isinstance(self.state, SeriesLoadState):
            raise TypeError("state must be a SeriesLoadState")
        if not all(
            isinstance(item, NormalizedObservation)
            for item in self.observations
        ):
            raise TypeError(
                "observations must contain "
                "NormalizedObservation values"
            )
        if self.state is SeriesLoadState.LOADED:
            if not self.observations:
                raise ValueError(
                    "loaded series requires observations"
                )
            if self.error is not None:
                raise ValueError(
                    "loaded series cannot contain an error"
                )
        else:
            if self.observations:
                raise ValueError(
                    "unavailable series cannot contain observations"
                )
            if not isinstance(self.error, str) or not self.error.strip():
                raise ValueError(
                    "unavailable series requires an error"
                )


@dataclass(frozen=True, slots=True)
class InstitutionalRegimeRun:
    """Complete acquisition and assessment result for one decision time."""

    as_of: datetime
    provider: str
    loads: tuple[RegimeSeriesLoad, ...]
    assessment: EvidenceBasedRegimeResult

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if (
            self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
        ):
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.provider, str):
            raise TypeError("provider must be a string")
        normalized = self.provider.strip()
        if not normalized:
            raise ValueError("provider cannot be empty")
        if not self.loads:
            raise ValueError("loads cannot be empty")
        if not all(
            isinstance(item, RegimeSeriesLoad)
            for item in self.loads
        ):
            raise TypeError(
                "loads must contain RegimeSeriesLoad values"
            )
        if not isinstance(
            self.assessment,
            EvidenceBasedRegimeResult,
        ):
            raise TypeError(
                "assessment must be an "
                "EvidenceBasedRegimeResult"
            )
        if self.assessment.evidence.as_of != self.as_of:
            raise ValueError(
                "assessment evidence must use the run as_of"
            )
        object.__setattr__(self, "provider", normalized)

    @property
    def loaded_count(self) -> int:
        return sum(
            load.state is SeriesLoadState.LOADED
            for load in self.loads
        )

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count

    @property
    def degraded(self) -> bool:
        """Whether any requested evidence could not be retrieved."""

        return self.unavailable_count > 0


REGIME_FRED_REQUESTS = (
    RegimeSeriesRequest(
        signal="growth",
        series=FRED_SERIES["industrial_production"],
        limit=18,
    ),
    RegimeSeriesRequest(
        signal="inflation",
        series=FRED_SERIES["consumer_price_index"],
        limit=18,
    ),
    RegimeSeriesRequest(
        signal="policy",
        series=FRED_SERIES["federal_funds_rate"],
        limit=18,
    ),
    RegimeSeriesRequest(
        signal="liquidity",
        series=FRED_SERIES["federal_reserve_total_assets"],
        limit=60,
    ),
    RegimeSeriesRequest(
        signal="financial_stress",
        series=FRED_SERIES["financial_stress_index"],
        limit=8,
    ),
)

REGIME_FRED_REQUESTS_BY_SIGNAL: Mapping[
    str,
    RegimeSeriesRequest,
] = MappingProxyType(
    {request.signal: request for request in REGIME_FRED_REQUESTS}
)


class InstitutionalRegimePipeline:
    """Retrieve canonical evidence and classify one economic regime."""

    def __init__(
        self,
        provider: ObservationProvider,
        *,
        requests: tuple[RegimeSeriesRequest, ...] = (
            REGIME_FRED_REQUESTS
        ),
        builder: RegimeEvidenceBuilder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider, ObservationProvider):
            raise TypeError(
                "provider must implement ObservationProvider"
            )
        if not requests:
            raise ValueError("requests cannot be empty")
        if not all(
            isinstance(item, RegimeSeriesRequest)
            for item in requests
        ):
            raise TypeError(
                "requests must contain RegimeSeriesRequest values"
            )
        signals = [request.signal for request in requests]
        if len(signals) != len(set(signals)):
            raise ValueError("request signals must be unique")
        self.provider = provider
        self.requests = requests
        self.builder = builder or RegimeEvidenceBuilder()
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )

    def run(
        self,
        *,
        as_of: datetime,
    ) -> InstitutionalRegimeRun:
        """Run retrieval and assessment without synthetic fallback."""

        decision_time = self._aware_time(
            as_of,
            field_name="as_of",
        )
        loads: list[RegimeSeriesLoad] = []
        observations: list[NormalizedObservation] = []

        for request in self.requests:
            query = ObservationQuery(
                series=request.series,
                as_of=decision_time,
                limit=request.limit,
            )
            try:
                result = tuple(self.provider.fetch(query))
            except ProviderError as error:
                loads.append(
                    RegimeSeriesLoad(
                        request=request,
                        state=SeriesLoadState.UNAVAILABLE,
                        error=str(error),
                    )
                )
                continue

            if not result:
                loads.append(
                    RegimeSeriesLoad(
                        request=request,
                        state=SeriesLoadState.UNAVAILABLE,
                        error="provider returned no observations",
                    )
                )
                continue

            load = RegimeSeriesLoad(
                request=request,
                state=SeriesLoadState.LOADED,
                observations=result,
            )
            loads.append(load)
            observations.extend(result)

        assessment = self.builder.evaluate(
            observations,
            as_of=decision_time,
        )
        return InstitutionalRegimeRun(
            as_of=decision_time,
            provider=self.provider.name,
            loads=tuple(loads),
            assessment=assessment,
        )

    def run_current(self) -> InstitutionalRegimeRun:
        """Run at the configured timezone-aware current time."""

        return self.run(
            as_of=self._aware_time(
                self._clock(),
                field_name="clock",
            )
        )

    @staticmethod
    def _aware_time(
        value: object,
        *,
        field_name: str,
    ) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                f"{field_name} must be timezone-aware"
            )
        return value


def build_fred_regime_pipeline(
    *,
    provider: FREDProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> InstitutionalRegimePipeline:
    """Build the canonical U.S. regime pipeline using FRED."""

    return InstitutionalRegimePipeline(
        provider or FREDProvider(),
        clock=clock,
    )


__all__ = [
    "InstitutionalRegimePipeline",
    "InstitutionalRegimeRun",
    "REGIME_FRED_REQUESTS",
    "REGIME_FRED_REQUESTS_BY_SIGNAL",
    "RegimeSeriesLoad",
    "RegimeSeriesRequest",
    "SeriesLoadState",
    "build_fred_regime_pipeline",
]
