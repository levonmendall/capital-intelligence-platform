"""Canonical market participation authority.

Discovery is broader than committee, CIO, construction, and paper-allocation
authority. The versioned market-coverage registry is the sole machine authority
for promoting an exact instrument beyond observation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, is_dataclass, replace
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from cio.models import CandidateAssetClass
from governance.coverage_certification import (
    MarketCoverage,
    MarketCoverageRegistry,
    load_market_coverage,
)

DEFAULT_MARKET_COVERAGE_PATH = Path(
    os.getenv(
        "CAPITAL_INTELLIGENCE_MARKET_COVERAGE_REGISTRY",
        "config/market_coverage_registry.v1.json",
    )
).expanduser()


class MarketParticipationStage(str, Enum):
    OBSERVED = "observed"
    DECISION_CERTIFIED = "decision_certified"
    PAPER_ALLOCATABLE = "paper_allocatable"


@dataclass(frozen=True, slots=True)
class MarketParticipationAssessment:
    instrument_identifier: str
    market: str
    monitored: bool
    decision_certified: bool
    paper_allocatable: bool
    certification_identifier: str | None
    limitations: tuple[str, ...]
    registry_identifier: str

    @property
    def highest_stage(self) -> MarketParticipationStage | None:
        if self.paper_allocatable:
            return MarketParticipationStage.PAPER_ALLOCATABLE
        if self.decision_certified:
            return MarketParticipationStage.DECISION_CERTIFIED
        if self.monitored:
            return MarketParticipationStage.OBSERVED
        return None


_MARKET_BY_ASSET_CLASS = {
    CandidateAssetClass.US_EQUITY: "direct_us_equities",
    CandidateAssetClass.US_ETF: "direct_us_equities",
    CandidateAssetClass.INTERNATIONAL_EQUITY: "direct_international_equities",
    CandidateAssetClass.FIXED_INCOME: "direct_fixed_income_credit",
    CandidateAssetClass.CASH_EQUIVALENT: "direct_fixed_income_credit",
    CandidateAssetClass.COMMODITY: "direct_commodities_futures",
    CandidateAssetClass.FUTURE: "direct_commodities_futures",
    CandidateAssetClass.FX: "direct_spot_fx",
    CandidateAssetClass.CRYPTO: "direct_spot_crypto",
    CandidateAssetClass.REAL_ESTATE: "direct_real_estate_alternatives",
    CandidateAssetClass.ALTERNATIVE: "direct_real_estate_alternatives",
    CandidateAssetClass.OPTION: "direct_options_volatility",
    CandidateAssetClass.VOLATILITY: "direct_options_volatility",
}


class CanonicalMarketParticipationAuthority:
    """Enforce observed, decision-certified, and allocatable scopes separately."""

    def __init__(self, registry: MarketCoverageRegistry) -> None:
        if not isinstance(registry, MarketCoverageRegistry):
            raise TypeError("registry must be a MarketCoverageRegistry")
        self.registry = registry
        self._by_market = {item.market: item for item in registry.markets}
        self._allocatable_entry_by_instrument = {
            identifier: item
            for item in registry.markets
            for identifier in item.allocatable_instrument_identifiers
        }

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_MARKET_COVERAGE_PATH,
    ) -> "CanonicalMarketParticipationAuthority":
        return cls(load_market_coverage(path))

    @property
    def allocatable_instrument_identifiers(self) -> frozenset[str]:
        return frozenset(self._allocatable_entry_by_instrument)

    def assess(
        self,
        *,
        instrument_identifier: str,
        asset_class: CandidateAssetClass | None = None,
    ) -> MarketParticipationAssessment:
        identifier = str(instrument_identifier).strip()
        if not identifier:
            raise ValueError("instrument_identifier cannot be empty")
        exact = self._allocatable_entry_by_instrument.get(identifier)
        if exact is not None:
            return MarketParticipationAssessment(
                instrument_identifier=identifier,
                market=exact.market,
                monitored=exact.monitored,
                decision_certified=True,
                paper_allocatable=True,
                certification_identifier=exact.decision_certification_identifier,
                limitations=exact.limitations,
                registry_identifier=self.registry.identifier,
            )
        market = _MARKET_BY_ASSET_CLASS.get(asset_class)
        entry: MarketCoverage | None = self._by_market.get(market) if market else None
        if entry is None:
            return MarketParticipationAssessment(
                instrument_identifier=identifier,
                market="unclassified",
                monitored=False,
                decision_certified=False,
                paper_allocatable=False,
                certification_identifier=None,
                limitations=("Instrument is outside the classified market registry.",),
                registry_identifier=self.registry.identifier,
            )
        return MarketParticipationAssessment(
            instrument_identifier=identifier,
            market=entry.market,
            monitored=entry.monitored,
            decision_certified=False,
            paper_allocatable=False,
            certification_identifier=None,
            limitations=entry.limitations,
            registry_identifier=self.registry.identifier,
        )

    def filter_paper_allocatable(
        self,
        instruments: Iterable[object],
    ) -> tuple[object, ...]:
        selected = tuple(
            item
            for item in instruments
            if str(getattr(item, "instrument_identifier", "")).strip()
            in self.allocatable_instrument_identifiers
        )
        identifiers = tuple(
            str(getattr(item, "instrument_identifier", "")).strip()
            for item in selected
        )
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("paper authority contains duplicate instruments")
        return selected

    def require_complete_allocatable_set(self, instruments: Iterable[object]) -> None:
        available = {
            str(getattr(item, "instrument_identifier", "")).strip()
            for item in instruments
        }
        missing = sorted(self.allocatable_instrument_identifiers - available)
        if missing:
            raise ValueError(
                "certified paper-allocatable set is incomplete: "
                + ", ".join(missing)
            )

    def decision_authority_universe(self, universe):
        instruments = tuple(getattr(universe, "instruments", ()))
        self.require_complete_allocatable_set(instruments)
        selected = self.filter_paper_allocatable(instruments)
        if not selected:
            raise ValueError("market registry contains no paper-allocatable instruments")
        limitations = tuple(
            dict.fromkeys(
                (
                    *tuple(getattr(universe, "limitations", ())),
                    "Committee, CIO, construction, and paper authority is limited to exact registry-listed instruments.",
                    "Observed direct markets remain intelligence-only until separately certified and paper-approved.",
                )
            )
        )
        if is_dataclass(universe):
            return replace(universe, instruments=selected, limitations=limitations)
        return SimpleNamespace(
            identifier=str(getattr(universe, "identifier", "")).strip(),
            instruments=selected,
            limitations=limitations,
        )


__all__ = [
    "CanonicalMarketParticipationAuthority",
    "DEFAULT_MARKET_COVERAGE_PATH",
    "MarketParticipationAssessment",
    "MarketParticipationStage",
]
