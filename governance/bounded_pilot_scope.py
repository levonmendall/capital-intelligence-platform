"""Exact capability authority for the configured governed paper universe.

The exact active paper universe is a versioned capability-certified instrument
boundary. This adapter makes that exact boundary available to the canonical
recommendation policy without granting authority to a symbol, venue, structure, or
economic exposure that is not present in the configured universe.

Historical use is explicitly a research-only current-policy overlay. It does not
pretend that a 2026 governance approval existed at an earlier market-data cutoff and
cannot promote policy or authorize execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cio.models import CandidateAssetClass, CandidateInstrument
from governance.asset_class_scope import (
    AssetClassApprovalState,
    AssetClassScopeAssessment,
    AssetClassScopeAuthority,
)


_EXPOSURE_ASSET_CLASSES: dict[str, CandidateAssetClass] = {
    "us_equity": CandidateAssetClass.US_EQUITY,
    "international_equity": CandidateAssetClass.INTERNATIONAL_EQUITY,
    "government_bonds": CandidateAssetClass.FIXED_INCOME,
    "investment_grade_credit": CandidateAssetClass.FIXED_INCOME,
    "high_yield_credit": CandidateAssetClass.FIXED_INCOME,
    "cash_treasury": CandidateAssetClass.CASH_EQUIVALENT,
    "broad_commodities": CandidateAssetClass.COMMODITY,
    "gold": CandidateAssetClass.COMMODITY,
    "foreign_exchange": CandidateAssetClass.FX,
    "crypto": CandidateAssetClass.CRYPTO,
    "real_estate": CandidateAssetClass.REAL_ESTATE,
    "managed_futures": CandidateAssetClass.ALTERNATIVE,
    "option_strategies": CandidateAssetClass.OPTION,
    "volatility": CandidateAssetClass.VOLATILITY,
    "market_neutral_alternatives": CandidateAssetClass.ALTERNATIVE,
}


def governed_asset_class_for_exposure(
    exposure: str,
    *,
    fallback: CandidateAssetClass,
) -> CandidateAssetClass:
    return _EXPOSURE_ASSET_CLASSES.get(str(exposure).strip().lower(), fallback)


@dataclass(frozen=True, slots=True)
class BoundedPilotInstrumentCapability:
    instrument_identifier: str
    symbol: str
    execution_asset_class: CandidateAssetClass
    governed_asset_class: CandidateAssetClass
    venue: str
    country_code: str
    instrument_type: str
    approval_identifier: str


class BoundedPilotCapabilityAuthority(AssetClassScopeAuthority):
    """Authorize exact instruments contained in one versioned active paper universe.

    The historical class name is retained for compatibility; the authority is no
    longer limited to the original static pilot symbols.
    """

    def __init__(
        self,
        capabilities: tuple[BoundedPilotInstrumentCapability, ...],
        *,
        universe_identifier: str,
        research_only: bool = False,
    ) -> None:
        if not capabilities:
            raise ValueError("active paper capability authority requires instruments")
        identifiers = tuple(item.instrument_identifier for item in capabilities)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("active paper capability identifiers must be unique")
        self._capabilities = {item.instrument_identifier: item for item in capabilities}
        self.universe_identifier = str(universe_identifier).strip()
        if not self.universe_identifier:
            raise ValueError("universe_identifier cannot be empty")
        self.research_only = bool(research_only)
        suffix = "research-current-policy" if self.research_only else "production"
        self.policy_version = (
            f"bounded-pilot-capability.v1:{suffix}:{self.universe_identifier}"
        )

    @classmethod
    def from_universe(
        cls,
        universe: Any,
        *,
        research_only: bool = False,
    ) -> "BoundedPilotCapabilityAuthority":
        universe_identifier = str(getattr(universe, "identifier", "")).strip()
        capabilities: list[BoundedPilotInstrumentCapability] = []
        for item in tuple(getattr(universe, "instruments", ())):
            execution_asset_class = getattr(item, "execution_asset_class")
            if not isinstance(execution_asset_class, CandidateAssetClass):
                raise TypeError("paper-universe execution asset class is invalid")
            exposure = str(getattr(item, "economic_exposure", "")).strip().lower()
            capabilities.append(
                BoundedPilotInstrumentCapability(
                    instrument_identifier=str(getattr(item, "instrument_identifier")),
                    symbol=str(getattr(item, "symbol")).upper(),
                    execution_asset_class=execution_asset_class,
                    governed_asset_class=governed_asset_class_for_exposure(
                        exposure,
                        fallback=execution_asset_class,
                    ),
                    venue=str(getattr(item, "venue")).upper(),
                    country_code=str(getattr(item, "country_code")).upper(),
                    instrument_type=str(getattr(item, "instrument_type")).lower(),
                    approval_identifier=(
                        str(getattr(item, "approval_identifier", "") or "").strip()
                        or (
                            f"paper-policy:{universe_identifier}:"
                            f"{str(getattr(item, 'symbol')).upper()}"
                        )
                    ),
                )
            )
        return cls(
            tuple(capabilities),
            universe_identifier=universe_identifier,
            research_only=research_only,
        )

    @classmethod
    def from_candidates(
        cls,
        candidates: tuple[object, ...],
        *,
        authority_identifier: str,
        research_only: bool = False,
    ) -> "BoundedPilotCapabilityAuthority":
        identifier = str(authority_identifier).strip()
        if not identifier:
            raise ValueError("authority_identifier cannot be empty")
        capabilities: list[BoundedPilotInstrumentCapability] = []
        for value in candidates:
            instrument = getattr(value, "instrument", value)
            if not isinstance(instrument, CandidateInstrument):
                raise TypeError("candidates must contain candidate records or instruments")
            governed = instrument.economic_exposure_class or instrument.asset_class
            capabilities.append(
                BoundedPilotInstrumentCapability(
                    instrument_identifier=instrument.instrument_id,
                    symbol=instrument.symbol,
                    execution_asset_class=instrument.asset_class,
                    governed_asset_class=governed,
                    venue=instrument.venue,
                    country_code=instrument.country_code,
                    instrument_type=instrument.instrument_type,
                    approval_identifier=(
                        f"screening-policy:{identifier}:{instrument.instrument_id}"
                    ),
                )
            )
        return cls(
            tuple(capabilities),
            universe_identifier=identifier,
            research_only=research_only,
        )

    def assess(
        self,
        instrument: CandidateInstrument,
        *,
        evaluated_at: datetime,
    ) -> AssetClassScopeAssessment:
        if not isinstance(instrument, CandidateInstrument):
            raise TypeError("instrument must be CandidateInstrument")
        if not isinstance(evaluated_at, datetime):
            raise TypeError("evaluated_at must be a datetime")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")

        capability = self._capabilities.get(instrument.instrument_id)
        if capability is None:
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=False,
                approval_identifier=None,
                approval_state=None,
                policy_version=self.policy_version,
                reasons=(
                    "instrument is outside the exact certified active paper universe",
                ),
            )

        reasons: list[str] = []
        if instrument.symbol != capability.symbol:
            reasons.append("symbol does not match the bounded capability record")
        if instrument.asset_class is not capability.governed_asset_class:
            reasons.append(
                "economic exposure class does not match the bounded capability record"
            )
        if instrument.venue != capability.venue:
            reasons.append("listing venue does not match the bounded capability record")
        if instrument.country_code != capability.country_code:
            reasons.append("listing country does not match the bounded capability record")
        if instrument.instrument_type != capability.instrument_type:
            reasons.append(
                "instrument structure does not match the bounded capability record"
            )
        if abs(instrument.leverage_multiplier) > 1.0 + 1e-9:
            reasons.append("active paper capability currently permits only unlevered exposure")

        if reasons:
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=False,
                approval_identifier=capability.approval_identifier,
                approval_state=AssetClassApprovalState.PAPER_ELIGIBLE,
                policy_version=self.policy_version,
                reasons=tuple(reasons),
            )

        mode = (
            "research-only current-policy overlay"
            if self.research_only
            else "production active-universe authority"
        )
        return AssetClassScopeAssessment(
            instrument_id=instrument.instrument_id,
            asset_class=instrument.asset_class,
            direct_recommendation_allowed=True,
            approval_identifier=capability.approval_identifier,
            approval_state=AssetClassApprovalState.PAPER_ELIGIBLE,
            policy_version=self.policy_version,
            reasons=(
                "exact instrument identity, exposure, venue, country, structure, "
                f"and leverage match the {mode}",
            ),
        )

    def coverage_payload(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "universe_identifier": self.universe_identifier,
            "covered_instrument_count": len(self._capabilities),
            "research_only": self.research_only,
            "execution_authorized": False,
            "real_money_authorized": False,
            "instrument_identifiers": sorted(self._capabilities),
        }


__all__ = [
    "BoundedPilotCapabilityAuthority",
    "BoundedPilotInstrumentCapability",
    "governed_asset_class_for_exposure",
]
