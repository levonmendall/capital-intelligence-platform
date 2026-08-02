"""Universal liquid-market recommendation policy with capability-based gates.

Every classified liquid public-market family may compete for capital. Production
paper ownership may additionally require an exact point-in-time instrument
certification, including for otherwise core U.S. securities. Research eligibility
and portfolio ownership therefore remain separate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Protocol

from cio.models import CandidateAssetClass, CandidateInstrument
from governance.asset_class_scope import (
    CORE_POLICY_ASSET_CLASSES,
    UNIVERSAL_GOVERNED_ASSET_CLASSES,
    AssetClassApprovalState,
    AssetClassScopeAuthority,
)


class PaperInstrumentParticipationAuthority(Protocol):
    """Exact-instrument paper authority consumed without a governance import cycle."""

    def assess(
        self,
        *,
        instrument_identifier: str,
        asset_class: CandidateAssetClass | None = None,
        instrument: object | None = None,
        evaluated_at: datetime | None = None,
    ) -> object: ...


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
    maximum_position_weight: float | None = None

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
        if self.maximum_position_weight is not None:
            value = self.maximum_position_weight
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("maximum_position_weight must be numeric or None")
            normalized = float(value)
            if not 0.0 < normalized <= 1.0:
                raise ValueError(
                    "maximum_position_weight must be above zero and at most 1.0"
                )
            object.__setattr__(
                self,
                "maximum_position_weight",
                round(normalized, 8),
            )

    @property
    def direct_recommendation_allowed(self) -> bool:
        return self.disposition is UniverseDisposition.DIRECT_RECOMMENDATION


@dataclass(frozen=True, slots=True)
class RecommendationUniversePolicy:
    """Universal scope with explicit liquidity, coverage, and capability governance."""

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
    market_participation_authority: PaperInstrumentParticipationAuthority | None = None

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
        if (
            self.market_participation_authority is None
            and bool(
                getattr(
                    self.asset_class_authority,
                    "require_market_participation_authority",
                    False,
                )
            )
        ):
            from governance.market_participation import (
                CanonicalMarketParticipationAuthority,
            )

            object.__setattr__(
                self,
                "market_participation_authority",
                CanonicalMarketParticipationAuthority.load(),
            )
        if self.market_participation_authority is not None and not callable(
            getattr(self.market_participation_authority, "assess", None)
        ):
            raise TypeError(
                "market_participation_authority must provide assess()"
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
        paper_certification_identifier: str | None = None
        paper_authority_kind: str | None = None
        paper_maximum_position_weight: float | None = None

        if self.market_participation_authority is not None:
            if as_of is None:
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=(
                        "instrument is intelligence-only because exact paper eligibility requires a point-in-time timestamp",
                    ),
                )
            participation = self.market_participation_authority.assess(
                instrument_identifier=instrument.instrument_id,
                asset_class=instrument.asset_class,
                instrument=instrument,
                evaluated_at=as_of,
            )
            if not bool(getattr(participation, "paper_allocatable", False)):
                limitations = tuple(
                    str(item).strip()
                    for item in tuple(getattr(participation, "limitations", ()))
                    if str(item).strip()
                )
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=tuple(
                        f"intelligence-only: {reason}" for reason in limitations
                    )
                    or (
                        "intelligence-only: no active complete instrument paper-eligibility certification exists",
                    ),
                )
            paper_authority_kind = str(
                getattr(participation, "authority_kind", "")
            ).strip() or None
            maximum_value = getattr(
                participation,
                "maximum_position_weight",
                None,
            )
            if maximum_value is not None:
                paper_maximum_position_weight = float(maximum_value)
            value = getattr(participation, "certification_identifier", None)
            if value is not None and str(value).strip():
                paper_certification_identifier = str(value).strip()
                approval_identifier = paper_certification_identifier

        governed_asset_class = self._governed_asset_class(instrument)
        if governed_asset_class is not None:
            if self.asset_class_authority is None:
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=(
                        "instrument is intelligence-only because its market or economic exposure lacks a configured capability authority",
                    ),
                    asset_class_approval_identifier=approval_identifier,
                    maximum_position_weight=paper_maximum_position_weight,
                )
            if as_of is None:
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=(
                        "instrument is intelligence-only because capability eligibility requires a point-in-time timestamp",
                    ),
                    asset_class_approval_identifier=approval_identifier,
                    asset_class_policy_version=self.asset_class_authority.policy_version,
                    maximum_position_weight=paper_maximum_position_weight,
                )
            governed_instrument = (
                instrument
                if instrument.asset_class is governed_asset_class
                else replace(instrument, asset_class=governed_asset_class)
            )
            scope = self.asset_class_authority.assess(
                governed_instrument, evaluated_at=as_of
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
                    maximum_position_weight=paper_maximum_position_weight,
                )
        else:
            scope_reasons = self._scope_reasons(instrument)
            if scope_reasons:
                return UniverseAssessment(
                    instrument_id=instrument.instrument_id,
                    disposition=UniverseDisposition.INTELLIGENCE_ONLY,
                    policy_version=self.version,
                    reasons=scope_reasons,
                    asset_class_approval_identifier=approval_identifier,
                    maximum_position_weight=paper_maximum_position_weight,
                )

        qualification_reasons: list[str] = []
        if (
            paper_authority_kind != "instrument_capability_certification"
            and instrument.average_daily_dollar_volume
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
                maximum_position_weight=paper_maximum_position_weight,
            )

        capability_reason = (
            "instrument satisfies scope, liquidity, freshness, coverage, and asset-class governance policy"
            if paper_certification_identifier is None
            else (
                "instrument satisfies exact paper certification "
                f"{paper_certification_identifier} plus scope, liquidity, freshness, coverage, and asset-class governance policy"
            )
        )
        return UniverseAssessment(
            instrument_id=instrument.instrument_id,
            disposition=UniverseDisposition.DIRECT_RECOMMENDATION,
            policy_version=self.version,
            reasons=(capability_reason,),
            asset_class_approval_identifier=approval_identifier,
            asset_class_approval_state=approval_state,
            asset_class_policy_version=asset_class_policy_version,
            maximum_position_weight=paper_maximum_position_weight,
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

    @staticmethod
    def _governed_asset_class(
        instrument: CandidateInstrument,
    ) -> CandidateAssetClass | None:
        exposure = instrument.economic_exposure_class
        if exposure in UNIVERSAL_GOVERNED_ASSET_CLASSES:
            return exposure
        if instrument.asset_class in UNIVERSAL_GOVERNED_ASSET_CLASSES:
            return instrument.asset_class
        complex_wrapper = (
            instrument.asset_class in CORE_POLICY_ASSET_CLASSES
            and (
                instrument.uses_derivatives
                or abs(instrument.leverage_multiplier) > 1.0 + 1e-9
                or instrument.instrument_type in {"future", "perpetual", "option"}
                or (instrument.replication_method or "").lower()
                in {"synthetic", "swap", "derivative"}
            )
        )
        return CandidateAssetClass.ALTERNATIVE if complex_wrapper else None

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
            f"{instrument.asset_class.value} is unclassified or outside the supported liquid public-market taxonomy",
        )


__all__ = [
    "PaperInstrumentParticipationAuthority",
    "RecommendationUniversePolicy",
    "UniverseAssessment",
    "UniverseDisposition",
]
