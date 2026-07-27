"""Versioned direct-recommendation universe policy.

Broader markets may supply evidence, but only eligible instruments may proceed to
a direct CIO portfolio action. Crypto, FX, and international equity identities
remain intelligence-only unless an explicit point-in-time asset-class approval
proves the complete paper-operating capability stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from cio.models import CandidateAssetClass, CandidateInstrument
from governance.asset_class_scope import (
    EXPANSION_ASSET_CLASSES,
    AssetClassApprovalState,
    AssetClassScopeAuthority,
)


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
    asset_class_approval_identifier: str | None = None
    asset_class_approval_state: AssetClassApprovalState | None = None
    asset_class_policy_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id.strip():
            raise ValueError("instrument_id cannot be empty")
        if not isinstance(self.disposition, UniverseDisposition):
            raise TypeError("disposition must be a UniverseDisposition")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if not isinstance(self.reasons, tuple) or not self.reasons or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")
        if self.asset_class_approval_identifier is not None and (
            not isinstance(self.asset_class_approval_identifier, str)
            or not self.asset_class_approval_identifier.strip()
        ):
            raise ValueError("asset_class_approval_identifier cannot be empty")
        if self.asset_class_approval_state is not None and not isinstance(
            self.asset_class_approval_state,
            AssetClassApprovalState,
        ):
            raise TypeError(
                "asset_class_approval_state must be AssetClassApprovalState"
            )
        if self.asset_class_policy_version is not None and (
            not isinstance(self.asset_class_policy_version, str)
            or not self.asset_class_policy_version.strip()
        ):
            raise ValueError("asset_class_policy_version cannot be empty")

    @property
    def direct_recommendation_allowed(self) -> bool:
        return self.disposition is UniverseDisposition.DIRECT_RECOMMENDATION


@dataclass(frozen=True, slots=True)
class RecommendationUniversePolicy:
    """Focused scope with explicit liquidity, coverage, and expansion governance."""

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
    asset_class_authority: AssetClassScopeAuthority | None = None

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
        if self.asset_class_authority is not None and not isinstance(
            self.asset_class_authority,
            AssetClassScopeAuthority,
        ):
            raise TypeError(
                "asset_class_authority must be an AssetClassScopeAuthority"
            )

    def evaluate(
        self,
        instrument: CandidateInstrument,
        *,
        as_of: datetime | None = None,
    ) -> UniverseAssessment:
        if not isinstance(instrument, CandidateInstrument):
            raise TypeError("instrument must be a CandidateInstrument")

        approval_identifier: str | None = None
        approval_state: AssetClassApprovalState | None = None
        asset_class_policy_version: str | None = None
        if instrument.asset_class in EXPANSION_ASSET_CLASSES:
            if self.asset_class_authority is None:
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=(
                        "expanded asset class is intelligence-only because no configured governance authority exists",
                    ),
                )
            if as_of is None:
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=(
                        "expanded asset class is intelligence-only because eligibility requires a point-in-time evaluation timestamp",
                    ),
                    asset_class_policy_version=(
                        self.asset_class_authority.policy_version
                    ),
                )
            scope = self.asset_class_authority.assess(
                instrument,
                evaluated_at=as_of,
            )
            approval_identifier = scope.approval_identifier
            approval_state = scope.approval_state
            asset_class_policy_version = scope.policy_version
            if not scope.direct_recommendation_allowed:
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=tuple(
                        f"intelligence-only: {reason}" for reason in scope.reasons
                    ),
                    asset_class_approval_identifier=approval_identifier,
                    asset_class_approval_state=approval_state,
                    asset_class_policy_version=asset_class_policy_version,
                )
        else:
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
                "average daily dollar volume is below the recommendation liquidity floor"
            )
        if instrument.data_age_hours > self.maximum_data_age_hours:
            qualification_reasons.append(
                "market data is older than the recommendation freshness limit"
            )
        if instrument.analytical_coverage < self.minimum_analytical_coverage:
            qualification_reasons.append(
                "analytical coverage is below the recommendation minimum"
            )
        if qualification_reasons:
            return UniverseAssessment(
                instrument_id=instrument.instrument_id,
                disposition=UniverseDisposition.INELIGIBLE,
                policy_version=self.version,
                reasons=tuple(qualification_reasons),
                asset_class_approval_identifier=approval_identifier,
                asset_class_approval_state=approval_state,
                asset_class_policy_version=asset_class_policy_version,
            )

        return UniverseAssessment(
            instrument_id=instrument.instrument_id,
            disposition=UniverseDisposition.DIRECT_RECOMMENDATION,
            policy_version=self.version,
            reasons=(
                "instrument satisfies scope, liquidity, freshness, coverage, and asset-class governance policy",
            ),
            asset_class_approval_identifier=approval_identifier,
            asset_class_approval_state=approval_state,
            asset_class_policy_version=asset_class_policy_version,
        )

    def require_direct_recommendation(
        self,
        instrument: CandidateInstrument,
        *,
        as_of: datetime | None = None,
    ) -> UniverseAssessment:
        assessment = self.evaluate(instrument, as_of=as_of)
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
                    "Treasury-equivalent duration exceeds the short-duration limit",
                )
            return ()

        return (
            f"{instrument.asset_class.value} is intelligence-only under the active recommendation policy",
        )


__all__ = [
    "RecommendationUniversePolicy",
    "UniverseAssessment",
    "UniverseDisposition",
]
