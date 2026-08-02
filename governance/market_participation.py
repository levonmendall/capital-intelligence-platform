"""Canonical market participation authority.

Discovery, committee review, and paper ownership remain separate. The current
registry instruments are bootstrap certifications, not a permanent closed list.
Any classified liquid instrument may become paper-allocatable through a complete,
active instrument capability certification.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, is_dataclass, replace
from datetime import datetime
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
from governance.instrument_paper_eligibility import (
    InstrumentPaperEligibilityAuthority,
    SQLiteInstrumentPaperEligibilityStore,
)

DEFAULT_MARKET_COVERAGE_PATH = Path(
    os.getenv(
        "CAPITAL_INTELLIGENCE_MARKET_COVERAGE_REGISTRY",
        "config/market_coverage_registry.v1.json",
    )
).expanduser()
DEFAULT_INSTRUMENT_PAPER_ELIGIBILITY_PATH = Path(
    os.getenv(
        "CAPITAL_INTELLIGENCE_INSTRUMENT_PAPER_ELIGIBILITY_DATABASE",
        "database/instrument-paper-eligibility.db",
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
    maximum_position_weight: float | None = None
    authority_kind: str = "market_registry"

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


def _instrument_identifier(item: object) -> str:
    value = getattr(item, "instrument_identifier", None)
    if value is None:
        value = getattr(item, "instrument_id", "")
    return str(value).strip()


def _instrument_asset_class(item: object) -> CandidateAssetClass | None:
    value = getattr(item, "asset_class", None)
    if value is None:
        value = getattr(item, "execution_asset_class", None)
    return value if isinstance(value, CandidateAssetClass) else None


class CanonicalMarketParticipationAuthority:
    """Enforce observed, certified, and paper-allocatable scopes separately."""

    def __init__(
        self,
        registry: MarketCoverageRegistry,
        *,
        instrument_authority: InstrumentPaperEligibilityAuthority | None = None,
    ) -> None:
        if not isinstance(registry, MarketCoverageRegistry):
            raise TypeError("registry must be a MarketCoverageRegistry")
        if instrument_authority is not None and not isinstance(
            instrument_authority, InstrumentPaperEligibilityAuthority
        ):
            raise TypeError(
                "instrument_authority must be InstrumentPaperEligibilityAuthority"
            )
        self.registry = registry
        self.instrument_authority = instrument_authority
        self._by_market = {item.market: item for item in registry.markets}
        self._bootstrap_entry_by_instrument = {
            identifier: item
            for item in registry.markets
            for identifier in item.allocatable_instrument_identifiers
        }

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_MARKET_COVERAGE_PATH,
        *,
        capability_database_path: str | Path | None = None,
    ) -> "CanonicalMarketParticipationAuthority":
        resolved_database: Path | None = None
        if capability_database_path is not None:
            resolved_database = Path(capability_database_path).expanduser()
        else:
            configured = os.getenv(
                "CAPITAL_INTELLIGENCE_INSTRUMENT_PAPER_ELIGIBILITY_DATABASE", ""
            ).strip()
            if configured:
                resolved_database = Path(configured).expanduser()
            elif DEFAULT_INSTRUMENT_PAPER_ELIGIBILITY_PATH.exists():
                resolved_database = DEFAULT_INSTRUMENT_PAPER_ELIGIBILITY_PATH
        instrument_authority = None
        if resolved_database is not None:
            instrument_authority = InstrumentPaperEligibilityAuthority(
                SQLiteInstrumentPaperEligibilityStore(resolved_database)
            )
        return cls(
            load_market_coverage(path),
            instrument_authority=instrument_authority,
        )

    @property
    def allocatable_instrument_identifiers(self) -> frozenset[str]:
        """Return bootstrap identifiers retained for current-pilot compatibility."""

        return frozenset(self._bootstrap_entry_by_instrument)

    def paper_allocatable_identifiers(
        self, *, evaluated_at: datetime | None = None
    ) -> frozenset[str]:
        identifiers = set(self.allocatable_instrument_identifiers)
        if self.instrument_authority is not None and evaluated_at is not None:
            identifiers.update(
                self.instrument_authority.active_identifiers(
                    evaluated_at=evaluated_at
                )
            )
        return frozenset(identifiers)

    def assess(
        self,
        *,
        instrument_identifier: str,
        asset_class: CandidateAssetClass | None = None,
        instrument: object | None = None,
        evaluated_at: datetime | None = None,
    ) -> MarketParticipationAssessment:
        identifier = str(instrument_identifier).strip()
        if not identifier:
            raise ValueError("instrument_identifier cannot be empty")
        exact = self._bootstrap_entry_by_instrument.get(identifier)
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
                authority_kind="bootstrap_certification",
            )

        resolved_asset_class = asset_class
        if resolved_asset_class is None and instrument is not None:
            resolved_asset_class = _instrument_asset_class(instrument)
        market = _MARKET_BY_ASSET_CLASS.get(resolved_asset_class)
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

        if (
            self.instrument_authority is not None
            and instrument is not None
            and evaluated_at is not None
        ):
            capability = self.instrument_authority.assess(
                instrument, evaluated_at=evaluated_at
            )
            if capability.paper_allocatable:
                return MarketParticipationAssessment(
                    instrument_identifier=identifier,
                    market=entry.market,
                    monitored=entry.monitored,
                    decision_certified=True,
                    paper_allocatable=True,
                    certification_identifier=capability.certification_identifier,
                    limitations=tuple(
                        dict.fromkeys((*entry.limitations, *capability.reasons))
                    ),
                    registry_identifier=self.registry.identifier,
                    maximum_position_weight=capability.maximum_position_weight,
                    authority_kind="instrument_capability_certification",
                )
            limitations = tuple(
                dict.fromkeys((*entry.limitations, *capability.reasons))
            )
        else:
            limitations = entry.limitations

        return MarketParticipationAssessment(
            instrument_identifier=identifier,
            market=entry.market,
            monitored=entry.monitored,
            decision_certified=False,
            paper_allocatable=False,
            certification_identifier=None,
            limitations=limitations,
            registry_identifier=self.registry.identifier,
        )

    def filter_paper_allocatable(
        self,
        instruments: Iterable[object],
        *,
        evaluated_at: datetime | None = None,
    ) -> tuple[object, ...]:
        selected: list[object] = []
        for item in instruments:
            identifier = _instrument_identifier(item)
            if not identifier:
                continue
            assessment = self.assess(
                instrument_identifier=identifier,
                asset_class=_instrument_asset_class(item),
                instrument=item,
                evaluated_at=evaluated_at,
            )
            if assessment.paper_allocatable:
                selected.append(item)
        identifiers = tuple(_instrument_identifier(item) for item in selected)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("paper authority contains duplicate instruments")
        return tuple(selected)

    def require_complete_allocatable_set(
        self,
        instruments: Iterable[object],
        *,
        evaluated_at: datetime | None = None,
    ) -> None:
        available = {_instrument_identifier(item) for item in instruments}
        required = self.paper_allocatable_identifiers(evaluated_at=evaluated_at)
        missing = sorted(required - available)
        if missing:
            raise ValueError(
                "certified paper-allocatable set is incomplete: "
                + ", ".join(missing)
            )

    def decision_authority_universe(
        self,
        universe,
        *,
        evaluated_at: datetime | None = None,
    ):
        instruments = tuple(getattr(universe, "instruments", ()))
        self.require_complete_allocatable_set(
            instruments, evaluated_at=evaluated_at
        )
        selected = self.filter_paper_allocatable(
            instruments, evaluated_at=evaluated_at
        )
        if not selected:
            raise ValueError(
                "no instrument currently satisfies paper-allocation authority"
            )
        limitations = tuple(
            dict.fromkeys(
                (
                    *tuple(getattr(universe, "limitations", ())),
                    "Portfolio authority is capability-based: bootstrap instruments and any additional instrument with a complete active certification may be owned.",
                    "Missing, expired, suspended, stale, illiquid, or structurally mismatched certifications remain fail-closed.",
                    "Capability certification changes paper eligibility only; the CIO, construction engine, and risk controls still determine whether and how much to own.",
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
    "DEFAULT_INSTRUMENT_PAPER_ELIGIBILITY_PATH",
    "DEFAULT_MARKET_COVERAGE_PATH",
    "MarketParticipationAssessment",
    "MarketParticipationStage",
]
