"""Versioned direct-recommendation universe policy.

Broader markets may supply evidence, but only eligible Version 1 instruments may
proceed to a direct CIO portfolio action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cio.models import CandidateAssetClass, CandidateInstrument


class UniverseDisposition(str, Enum):
    """How an instrument may participate in the system."""

    DIRECT_RECOMMENDATION = "direct_recommendation"
    INTELLIGENCE_ONLY = "intelligence_only"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True, slots=True)
class UniverseAssessment:
    """Auditable policy result for one instrument at one evidence boundary."""

    instrument_id: str
    disposition: UniverseDisposition
    policy_version: str
    reasons: tuple[str, ...]

    @property
    def direct_recommendation_allowed(self) -> bool:
        return self.disposition is UniverseDisposition.DIRECT_RECOMMENDATION


@dataclass(frozen=True, slots=True)
class RecommendationUniversePolicy:
    """Focused Version 1 scope with explicit liquidity and coverage floors."""

    version: str = "recommendation-universe.v1"
    minimum_average_daily_dollar_volume: float = 5_000_000.0
    maximum_data_age_hours: float = 24.0
    minimum_analytical_coverage: float = 0.80
    maximum_treasury_duration_years: float = 1.25
    us_venues: tuple[str, ...] = (
        "NASDAQ",
        "NYSE",
        "NYSEARCA",
        "NYSEAMERICAN",
        "CBOE",
        "BATS",
    )

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        if self.minimum_average_daily_dollar_volume < 0:
            raise ValueError(
                "minimum_average_daily_dollar_volume cannot be negative"
            )
        if self.maximum_data_age_hours <= 0:
            raise ValueError("maximum_data_age_hours must be positive")
        if not 0 <= self.minimum_analytical_coverage <= 1:
            raise ValueError(
                "minimum_analytical_coverage must be between 0 and 1"
            )
        if self.maximum_treasury_duration_years <= 0:
            raise ValueError("maximum_treasury_duration_years must be positive")
        normalized = tuple(item.strip().upper() for item in self.us_venues)
        if any(not item for item in normalized):
            raise ValueError("us_venues cannot contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("us_venues cannot contain duplicates")
        object.__setattr__(self, "us_venues", normalized)

    def evaluate(self, instrument: CandidateInstrument) -> UniverseAssessment:
        if not isinstance(instrument, CandidateInstrument):
            raise TypeError("instrument must be a CandidateInstrument")

        scope_reasons = self._scope_reasons(instrument)
        if scope_reasons:
            return UniverseAssessment(
                instrument_id=instrument.instrument_id,
                disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                policy_version=self.version,
                reasons=scope_reasons,
            )

        qualification_reasons: list[str] = []
        if (
            instrument.average_daily_dollar_volume
            < self.minimum_average_daily_dollar_volume
        ):
            qualification_reasons.append(
                "average daily dollar volume is below the Version 1 liquidity floor"
            )
        if instrument.data_age_hours > self.maximum_data_age_hours:
            qualification_reasons.append(
                "market data is older than the Version 1 freshness limit"
            )
        if instrument.analytical_coverage < self.minimum_analytical_coverage:
            qualification_reasons.append(
                "analytical coverage is below the Version 1 minimum"
            )
        if qualification_reasons:
            return UniverseAssessment(
                instrument_id=instrument.instrument_id,
                disposition=UniverseDisposition.INELIGIBLE,
                policy_version=self.version,
                reasons=tuple(qualification_reasons),
            )

        return UniverseAssessment(
            instrument_id=instrument.instrument_id,
            disposition=UniverseDisposition.DIRECT_RECOMMENDATION,
            policy_version=self.version,
            reasons=(
                "instrument satisfies Version 1 scope, liquidity, freshness, and coverage policy",
            ),
        )

    def require_direct_recommendation(
        self,
        instrument: CandidateInstrument,
    ) -> UniverseAssessment:
        assessment = self.evaluate(instrument)
        if not assessment.direct_recommendation_allowed:
            detail = "; ".join(assessment.reasons)
            raise ValueError(
                f"instrument is not eligible for direct recommendation: {detail}"
            )
        return assessment

    def _scope_reasons(
        self,
        instrument: CandidateInstrument,
    ) -> tuple[str, ...]:
        if instrument.asset_class in {
            CandidateAssetClass.US_EQUITY,
            CandidateAssetClass.US_ETF,
        }:
            reasons: list[str] = []
            if instrument.country_code != "US":
                reasons.append("instrument is not a U.S. listing")
            if instrument.venue not in self.us_venues:
                reasons.append("listing venue is outside the approved U.S. venue set")
            return tuple(reasons)

        if instrument.asset_class is CandidateAssetClass.CASH_EQUIVALENT:
            if not instrument.is_us_treasury:
                return (
                    "cash-equivalent recommendation is not identified as a U.S. Treasury equivalent",
                )
            if instrument.effective_duration_years is None:
                return (
                    "Treasury-equivalent duration is unavailable",
                )
            if (
                instrument.effective_duration_years
                > self.maximum_treasury_duration_years
            ):
                return (
                    "Treasury-equivalent duration exceeds the Version 1 short-duration limit",
                )
            return ()

        return (
            f"{instrument.asset_class.value} is intelligence-only in Version 1",
        )


__all__ = [
    "RecommendationUniversePolicy",
    "UniverseAssessment",
    "UniverseDisposition",
]