"""Global opportunity ranking and cash-competition context.

This is portfolio context, not investment authority. It ranks governed candidates on
forward leadership/economics so the CIO can compare marginal uses of capital across
asset classes instead of treating cash as the residual default.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import exp, isfinite, log1p
from typing import Any, Sequence

from cio.models import CandidateAssetClass
from intelligence.global_leadership import assess_global_leadership_economics
from intelligence.theme_successor import theme_successor_score


class GlobalOpportunityDomain(str, Enum):
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    CREDIT = "credit"
    CURRENCY = "currency"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    REAL_ESTATE = "real_estate"
    VOLATILITY = "volatility"
    ALTERNATIVE = "alternative"
    CASH = "cash"
    OTHER = "other"


class CashCompetitionState(str, Enum):
    REQUIRED_RESERVE_ONLY = "required_reserve_only"
    CASH_LEADING_ESTIMATE = "cash_leading_estimate"
    DEPLOYMENT_OPPORTUNITY = "deployment_opportunity"


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("global rotation value must be finite")
    return round(max(low, min(high, number)), 8)


def opportunity_domain(candidate: object) -> GlobalOpportunityDomain:
    instrument = getattr(candidate, "instrument", candidate)
    asset_class = getattr(instrument, "economic_exposure_class", None) or getattr(
        instrument, "asset_class", CandidateAssetClass.OTHER
    )
    if asset_class in {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.US_ETF,
    }:
        return GlobalOpportunityDomain.EQUITY
    if asset_class is CandidateAssetClass.FIXED_INCOME:
        name = str(getattr(instrument, "name", "")).lower()
        return (
            GlobalOpportunityDomain.CREDIT
            if any(token in name for token in ("credit", "corporate", "high yield"))
            else GlobalOpportunityDomain.FIXED_INCOME
        )
    if asset_class is CandidateAssetClass.FX:
        return GlobalOpportunityDomain.CURRENCY
    if asset_class is CandidateAssetClass.CASH_EQUIVALENT:
        return GlobalOpportunityDomain.CASH
    if asset_class is CandidateAssetClass.COMMODITY:
        return GlobalOpportunityDomain.COMMODITY
    if asset_class is CandidateAssetClass.CRYPTO:
        return GlobalOpportunityDomain.CRYPTO
    if asset_class is CandidateAssetClass.REAL_ESTATE:
        return GlobalOpportunityDomain.REAL_ESTATE
    if asset_class in {CandidateAssetClass.VOLATILITY, CandidateAssetClass.OPTION}:
        return GlobalOpportunityDomain.VOLATILITY
    if asset_class in {CandidateAssetClass.ALTERNATIVE, CandidateAssetClass.FUTURE}:
        return GlobalOpportunityDomain.ALTERNATIVE
    return GlobalOpportunityDomain.OTHER


def _horizon_return(annual_return: float, horizon_days: int) -> float:
    if annual_return <= -1.0:
        return -1.0
    return exp(log1p(annual_return) * horizon_days / 365.25) - 1.0


@dataclass(frozen=True, slots=True)
class GlobalOpportunitySignal:
    candidate_identifier: str
    domain: GlobalOpportunityDomain
    rank: int
    score: float
    leadership_state: str
    leadership_score: float
    mispriced_change_state: str
    mispriced_change_score: float
    forward_impulse: float
    expected_return_edge: float
    evidence_score: float
    evidence_identifiers: tuple[str, ...]
    theme_successor_score: float = 0.0
    theme_successor_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_identifier.strip():
            raise ValueError("candidate_identifier cannot be empty")
        if not isinstance(self.domain, GlobalOpportunityDomain):
            raise TypeError("domain must be GlobalOpportunityDomain")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be positive")
        object.__setattr__(self, "score", _clip(self.score))
        object.__setattr__(self, "leadership_score", _clip(self.leadership_score))
        object.__setattr__(
            self,
            "mispriced_change_score",
            _clip(self.mispriced_change_score, -1.0, 1.0),
        )
        object.__setattr__(self, "evidence_score", _clip(self.evidence_score))
        object.__setattr__(self, "theme_successor_score", _clip(self.theme_successor_score))
        object.__setattr__(
            self,
            "evidence_identifiers",
            tuple(
                dict.fromkeys(
                    str(item).strip()
                    for item in self.evidence_identifiers
                    if str(item).strip()
                )
            ),
        )
        object.__setattr__(
            self,
            "theme_successor_sources",
            tuple(
                dict.fromkeys(
                    str(item).strip()
                    for item in self.theme_successor_sources
                    if str(item).strip()
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "domain": self.domain.value,
            "rank": self.rank,
            "score": self.score,
            "leadership_state": self.leadership_state,
            "leadership_score": self.leadership_score,
            "mispriced_change_state": self.mispriced_change_state,
            "mispriced_change_score": self.mispriced_change_score,
            "forward_impulse": self.forward_impulse,
            "expected_return_edge": self.expected_return_edge,
            "evidence_score": self.evidence_score,
            "theme_successor_score": self.theme_successor_score,
            "theme_successor_sources": list(self.theme_successor_sources),
            "evidence_identifiers": list(self.evidence_identifiers),
        }


@dataclass(frozen=True, slots=True)
class GlobalRotationContext:
    as_of: datetime
    signals: tuple[GlobalOpportunitySignal, ...]
    cash_expected_return: float
    minimum_cash_weight: float
    current_cash_weight: float
    excess_cash_weight: float
    cash_competition_state: CashCompetitionState
    policy_version: str = "global-opportunity-rotation-context.v1"
    authorizes_capital: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.signals, tuple) or not all(
            isinstance(item, GlobalOpportunitySignal) for item in self.signals
        ):
            raise TypeError("signals must contain GlobalOpportunitySignal values")
        identifiers = tuple(item.candidate_identifier for item in self.signals)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("global rotation signals must be unique by candidate")
        ranks = tuple(item.rank for item in self.signals)
        if ranks and ranks != tuple(range(1, len(ranks) + 1)):
            raise ValueError("global rotation signal ranks must be contiguous and ordered")
        object.__setattr__(self, "minimum_cash_weight", _clip(self.minimum_cash_weight))
        object.__setattr__(self, "current_cash_weight", _clip(self.current_cash_weight))
        object.__setattr__(self, "excess_cash_weight", _clip(self.excess_cash_weight))
        expected_excess = round(
            max(0.0, self.current_cash_weight - self.minimum_cash_weight),
            8,
        )
        if abs(self.excess_cash_weight - expected_excess) > 1e-8:
            raise ValueError("excess cash must equal current cash less the required reserve")
        if not isinstance(self.cash_competition_state, CashCompetitionState):
            raise TypeError("cash_competition_state must be CashCompetitionState")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if self.authorizes_capital:
            raise ValueError("global rotation context cannot authorize capital")

    @property
    def by_candidate(self) -> dict[str, GlobalOpportunitySignal]:
        return {item.candidate_identifier: item for item in self.signals}

    @property
    def strongest(self) -> GlobalOpportunitySignal | None:
        return self.signals[0] if self.signals else None

    def replacement_for(self, candidate_identifier: str) -> GlobalOpportunitySignal | None:
        current = self.by_candidate.get(candidate_identifier)
        for item in self.signals:
            if item.candidate_identifier == candidate_identifier or item.expected_return_edge <= 0.0:
                continue
            if current is None or item.score >= current.score + 0.10:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        strongest = self.strongest
        return {
            "as_of": self.as_of.isoformat(),
            "policy_version": self.policy_version,
            "cash_expected_return": self.cash_expected_return,
            "minimum_cash_weight": self.minimum_cash_weight,
            "current_cash_weight": self.current_cash_weight,
            "excess_cash_weight": self.excess_cash_weight,
            "cash_competition_state": self.cash_competition_state.value,
            "strongest_candidate_identifier": (
                None if strongest is None else strongest.candidate_identifier
            ),
            "strongest_domain": None if strongest is None else strongest.domain.value,
            "signals": [item.to_dict() for item in self.signals],
            "investment_authority": False,
            "construction_authority": False,
            "execution_authority": False,
        }


def _forward_impulse(bundle: object | None) -> float:
    if bundle is None:
        return 0.0
    value = sum(
        float(item.expected_return_impact) * float(item.confidence)
        for item in tuple(getattr(bundle, "signals", ()) or ())
        if not str(getattr(item, "identifier", "")).startswith(
            "signal:global-opportunity-radar:"
        )
        and not str(getattr(item, "identifier", "")).startswith(
            "signal:theme-successor:"
        )
    )
    return max(-0.10, min(0.10, value))


def _score(candidate: object, bundle: object | None) -> tuple[float, dict[str, object]]:
    successor_score, successor_evidence = theme_successor_score(bundle)
    successor_sources: tuple[str, ...] = ()
    if bundle is not None:
        successor_sources = tuple(
            dict.fromkeys(
                diagnostic.split(" <- ", 1)[1].split(";", 1)[0].strip()
                for diagnostic in tuple(getattr(bundle, "diagnostics", ()) or ())
                if diagnostic.startswith("Theme successor rotation:") and " <- " in diagnostic
            )
        )
    if bundle is None:
        leadership_state = "unavailable"
        leadership_score = 0.0
        mispricing_state = "unavailable"
        mispricing_score = 0.0
        evidence_ids = tuple(getattr(candidate, "evidence_identifiers", ()) or ())
    else:
        leadership = assess_global_leadership_economics(bundle)
        leadership_state = leadership.state.value
        leadership_score = leadership.leadership_score
        mispricing_state = leadership.mispriced_change_state
        mispricing_score = leadership.mispriced_change_score
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *tuple(getattr(candidate, "evidence_identifiers", ()) or ()),
                    *leadership.evidence_identifiers,
                    *successor_evidence,
                )
            )
        )
    impulse = _forward_impulse(bundle)
    horizon_alt = _horizon_return(
        float(getattr(candidate, "opportunity_cost_return", 0.0)),
        int(getattr(candidate, "decision_horizon_days", 365)),
    )
    edge = float(getattr(candidate, "net_expected_return", 0.0)) - horizon_alt
    evidence = float(
        getattr(getattr(candidate, "evidence_quality", None), "score", 0.0)
    )
    leadership_component = leadership_score
    mispricing_component = _clip(0.5 + 0.5 * mispricing_score)
    forward_component = _clip(0.5 + impulse / 0.10)
    edge_component = _clip(0.5 + edge / 0.10)
    base = (
        0.28 * leadership_component
        + 0.24 * mispricing_component
        + 0.20 * forward_component
        + 0.18 * edge_component
        + 0.10 * evidence
    )
    # Structural-theme successor evidence raises attention/rank by at most ten
    # percentage points. It never changes expected return or the robust-edge test.
    total = _clip(base + 0.10 * successor_score)
    if leadership_state == "deteriorating":
        total = _clip(total - 0.22)
    return total, {
        "leadership_state": leadership_state,
        "leadership_score": leadership_score,
        "mispricing_state": mispricing_state,
        "mispricing_score": mispricing_score,
        "forward_impulse": impulse,
        "edge": edge,
        "evidence": evidence,
        "evidence_ids": evidence_ids,
        "theme_successor_score": successor_score,
        "theme_successor_sources": successor_sources,
    }


def build_global_rotation_context(
    *,
    candidates: Sequence[object],
    specialist_contexts: Sequence[object],
    portfolio: object,
    minimum_cash_weight: float,
) -> GlobalRotationContext:
    context_map = {
        str(getattr(item, "candidate_identifier")): item for item in specialist_contexts
    }
    ranked: list[tuple[object, float, dict[str, object]]] = []
    for candidate in candidates:
        context = context_map.get(str(getattr(candidate, "identifier")))
        bundle = None if context is None else getattr(context, "forward_intelligence", None)
        score, details = _score(candidate, bundle)
        ranked.append((candidate, score, details))
    ranked.sort(
        key=lambda item: (
            item[1],
            float(item[2]["edge"]),
            float(item[2]["evidence"]),
            str(getattr(getattr(item[0], "instrument", None), "symbol", "")),
        ),
        reverse=True,
    )
    signals = tuple(
        GlobalOpportunitySignal(
            candidate_identifier=str(getattr(candidate, "identifier")),
            domain=opportunity_domain(candidate),
            rank=rank,
            score=score,
            leadership_state=str(details["leadership_state"]),
            leadership_score=float(details["leadership_score"]),
            mispriced_change_state=str(details["mispricing_state"]),
            mispriced_change_score=float(details["mispricing_score"]),
            forward_impulse=float(details["forward_impulse"]),
            expected_return_edge=float(details["edge"]),
            evidence_score=float(details["evidence"]),
            evidence_identifiers=tuple(details["evidence_ids"]),
            theme_successor_score=float(details["theme_successor_score"]),
            theme_successor_sources=tuple(details["theme_successor_sources"]),
        )
        for rank, (candidate, score, details) in enumerate(ranked, start=1)
    )
    minimum_cash = _clip(float(minimum_cash_weight))
    current_cash = _clip(float(getattr(portfolio, "cash_weight", 0.0)))
    excess = round(max(0.0, current_cash - minimum_cash), 8)
    deployable_signal = next(
        (
            item
            for item in signals
            if item.expected_return_edge > 0.0 and item.score >= 0.40
        ),
        None,
    )
    if excess <= 1e-9:
        cash_state = CashCompetitionState.REQUIRED_RESERVE_ONLY
    elif deployable_signal is not None:
        cash_state = CashCompetitionState.DEPLOYMENT_OPPORTUNITY
    else:
        cash_state = CashCompetitionState.CASH_LEADING_ESTIMATE
    as_of = getattr(portfolio, "as_of", None)
    if not isinstance(as_of, datetime):
        raise TypeError("portfolio as_of must be a datetime")
    return GlobalRotationContext(
        as_of=as_of,
        signals=signals,
        cash_expected_return=float(getattr(portfolio, "cash_expected_return", 0.0)),
        minimum_cash_weight=minimum_cash,
        current_cash_weight=current_cash,
        excess_cash_weight=excess,
        cash_competition_state=cash_state,
    )


__all__ = [
    "CashCompetitionState",
    "GlobalOpportunityDomain",
    "GlobalOpportunitySignal",
    "GlobalRotationContext",
    "build_global_rotation_context",
    "opportunity_domain",
]
