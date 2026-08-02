"""Canonical market participation authority.

The registry certifies markets and the active paper-universe publication certifies
specific executable instruments.  Exact legacy instrument lists remain supported,
but they are no longer the only route to committee, CIO, construction, or paper
allocation authority.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, is_dataclass, replace
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from cio.models import CandidateAssetClass
from governance.bounded_pilot_scope import governed_asset_class_for_exposure
from governance.coverage_certification import (
    AllocationAuthority,
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
_DERIVATIVE_TYPES = frozenset(
    {"future", "perpetual", "option", "forward", "swap", "warrant", "right"}
)


def _instrument_identifier(item: object) -> str:
    return str(getattr(item, "instrument_identifier", "")).strip()


def _execution_asset_class(item: object) -> CandidateAssetClass | None:
    value = getattr(item, "execution_asset_class", None)
    if isinstance(value, CandidateAssetClass):
        return value
    try:
        return CandidateAssetClass(str(value))
    except (TypeError, ValueError):
        return None


def _governed_asset_class(item: object) -> CandidateAssetClass | None:
    execution = _execution_asset_class(item)
    if execution is None:
        return None
    return governed_asset_class_for_exposure(
        str(getattr(item, "economic_exposure", "")),
        fallback=execution,
    )


class CanonicalMarketParticipationAuthority:
    """Resolve exact-list and active-capability paper authority independently."""

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
        """Return legacy exact-list identifiers, not the dynamic active universe."""

        return frozenset(self._allocatable_entry_by_instrument)

    def _entry_for_asset_class(
        self, asset_class: CandidateAssetClass | None
    ) -> MarketCoverage | None:
        market = _MARKET_BY_ASSET_CLASS.get(asset_class)
        return self._by_market.get(market) if market else None

    def assess(
        self,
        *,
        instrument_identifier: str,
        asset_class: CandidateAssetClass | None = None,
    ) -> MarketParticipationAssessment:
        """Assess registry scope without inventing instrument capability evidence.

        Dynamic paper allocatability requires the full active-universe instrument
        object and is therefore resolved by :meth:`filter_paper_allocatable`.
        """

        identifier = str(instrument_identifier).strip()
        if not identifier:
            raise ValueError("instrument_identifier cannot be empty")
        exact = self._allocatable_entry_by_instrument.get(identifier)
        if exact is not None:
            return MarketParticipationAssessment(
                instrument_identifier=identifier,
                market=exact.market,
                monitored=exact.monitored,
                decision_certified=exact.decision_certified,
                paper_allocatable=True,
                certification_identifier=exact.decision_certification_identifier,
                limitations=exact.limitations,
                registry_identifier=self.registry.identifier,
            )
        entry = self._entry_for_asset_class(asset_class)
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
            decision_certified=entry.decision_certified,
            paper_allocatable=False,
            certification_identifier=entry.decision_certification_identifier,
            limitations=entry.limitations,
            registry_identifier=self.registry.identifier,
        )

    def _active_capability_entry(self, item: object) -> MarketCoverage | None:
        entry = self._entry_for_asset_class(_governed_asset_class(item))
        if (
            entry is None
            or not entry.decision_certified
            or entry.allocation_authority
            is not AllocationAuthority.ACTIVE_UNIVERSE_CAPABILITY
        ):
            return None
        return entry

    @staticmethod
    def _complete_active_capability(
        item: object,
        *,
        universe_identifier: str,
    ) -> bool:
        identifier = _instrument_identifier(item)
        if not identifier:
            return False
        execution = _execution_asset_class(item)
        if execution is None or execution is CandidateAssetClass.OTHER:
            return False
        profile_builder = getattr(item, "profile", None)
        if not callable(profile_builder):
            # A screening candidate is analysis evidence, not an execution capability
            # publication.  Only the exact active-universe instrument contract can
            # promote it to paper allocation.
            return False
        try:
            profile = profile_builder(universe_identifier=universe_identifier)
        except (TypeError, ValueError, KeyError):
            return False
        if str(getattr(profile, "instrument_identifier", "")).strip() != identifier:
            return False
        approval_state = getattr(getattr(profile, "approval_state", None), "value", None)
        if approval_state != "paper_eligible":
            return False
        required_text = (
            "approval_identifier",
            "custody_settlement_identifier",
            "execution_model_version",
        )
        if any(not str(getattr(profile, name, "") or "").strip() for name in required_text):
            return False
        if getattr(profile, "trading_session_model", None) is None:
            return False
        leverage = getattr(profile, "gross_leverage", None)
        if (
            isinstance(leverage, bool)
            or not isinstance(leverage, (int, float))
            or not math.isfinite(float(leverage))
            or float(leverage) <= 0.0
            or float(leverage) > 1.0 + 1e-9
        ):
            return False
        instrument_type = str(getattr(profile, "instrument_type", "")).strip().lower()
        if not instrument_type:
            return False
        if instrument_type in _DERIVATIVE_TYPES:
            for name in (
                "contract_model_version",
                "margin_model_version",
                "lifecycle_model_version",
            ):
                if not str(getattr(profile, name, "") or "").strip():
                    return False
            if instrument_type in {"future", "perpetual"} and not str(
                getattr(profile, "roll_model_version", "") or ""
            ).strip():
                return False
            if not bool(getattr(profile, "defined_risk", False)):
                return False
        return True

    def filter_paper_allocatable(
        self,
        instruments: Iterable[object],
        *,
        universe_identifier: str | None = None,
    ) -> tuple[object, ...]:
        """Select every exact-listed or active-capability-certified instrument."""

        values = tuple(instruments)
        resolved_identifier = str(universe_identifier or "").strip()
        if not resolved_identifier:
            resolved_identifier = "active-paper-universe"
        selected: list[object] = []
        for item in values:
            identifier = _instrument_identifier(item)
            if not identifier:
                continue
            if identifier in self._allocatable_entry_by_instrument:
                selected.append(item)
                continue
            if self._active_capability_entry(item) is None:
                continue
            if self._complete_active_capability(
                item,
                universe_identifier=resolved_identifier,
            ):
                selected.append(item)
        identifiers = tuple(_instrument_identifier(item) for item in selected)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("paper authority contains duplicate instruments")
        return tuple(selected)

    def require_complete_allocatable_set(self, instruments: Iterable[object]) -> None:
        """Compatibility audit for legacy exact-list instruments.

        This method is no longer called by the canonical decision path.  A missing
        legacy wrapper cannot block a complete active capability universe.
        """

        available = {_instrument_identifier(item) for item in instruments}
        missing = sorted(self.allocatable_instrument_identifiers - available)
        if missing:
            raise ValueError(
                "certified exact-list paper set is incomplete: " + ", ".join(missing)
            )

    def decision_authority_universe(self, universe):
        instruments = tuple(getattr(universe, "instruments", ()))
        universe_identifier = str(getattr(universe, "identifier", "")).strip()
        if not universe_identifier:
            raise ValueError("paper universe identifier cannot be empty")
        selected = self.filter_paper_allocatable(
            instruments,
            universe_identifier=universe_identifier,
        )
        if not selected:
            raise ValueError(
                "market registry and active capability publication contain no "
                "paper-allocatable instruments"
            )
        limitations = tuple(
            dict.fromkeys(
                (
                    *tuple(getattr(universe, "limitations", ())),
                    "Paper authority is capability-based: every selected instrument must be decision-certified and complete in the exact active-universe publication.",
                    "Assets without complete identity, evidence, execution, custody, settlement, and lifecycle capability remain analysis-only.",
                )
            )
        )
        if is_dataclass(universe):
            return replace(universe, instruments=selected, limitations=limitations)
        return SimpleNamespace(
            identifier=universe_identifier,
            instruments=selected,
            limitations=limitations,
        )


__all__ = [
    "CanonicalMarketParticipationAuthority",
    "DEFAULT_MARKET_COVERAGE_PATH",
    "MarketParticipationAssessment",
    "MarketParticipationStage",
]
