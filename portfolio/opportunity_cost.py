"""Explain where capital comes from and what a new allocation gives up."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from portfolio.models import (
    PortfolioMandate,
    PortfolioProposal,
    PortfolioSnapshot,
)


class FundingSourceType(str, Enum):
    EXCESS_CASH = "excess_cash"
    POSITION_REDUCTION = "position_reduction"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _weight(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    return round(normalized, 6)


@dataclass(frozen=True, slots=True)
class OpportunityCostPolicy:
    """Versioned funding-order policy that never selects a sale silently."""

    version: str = "opportunity-cost.v1"
    use_excess_cash_first: bool = True
    minimum_material_weight: float = 0.001

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        if not isinstance(self.use_excess_cash_first, bool):
            raise TypeError("use_excess_cash_first must be a bool")
        object.__setattr__(
            self,
            "minimum_material_weight",
            _weight(
                self.minimum_material_weight,
                field_name="minimum_material_weight",
            ),
        )
        if self.minimum_material_weight == 0.0:
            raise ValueError("minimum_material_weight must be positive")


@dataclass(frozen=True, slots=True)
class FundingCandidate:
    """An explicitly approved existing position that may fund a proposal."""

    position_identifier: str
    maximum_reduction: float
    priority: int
    reason: str
    trade_off: str

    def __post_init__(self) -> None:
        for field_name in (
            "position_identifier",
            "reason",
            "trade_off",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "maximum_reduction",
            _weight(
                self.maximum_reduction,
                field_name="maximum_reduction",
            ),
        )
        if self.maximum_reduction == 0.0:
            raise ValueError("maximum_reduction must be positive")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an int")
        if self.priority < 1:
            raise ValueError("priority must be positive")


@dataclass(frozen=True, slots=True)
class CapitalFundingSource:
    identifier: str
    source_type: FundingSourceType
    redirected_weight: float
    explanation: str
    trade_off: str

    def __post_init__(self) -> None:
        for field_name in ("identifier", "explanation", "trade_off"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.source_type, FundingSourceType):
            raise TypeError("source_type must be a FundingSourceType")
        object.__setattr__(
            self,
            "redirected_weight",
            _weight(
                self.redirected_weight,
                field_name="redirected_weight",
            ),
        )
        if self.redirected_weight == 0.0:
            raise ValueError("redirected_weight must be positive")


@dataclass(frozen=True, slots=True)
class OpportunityCostAssessment:
    """A non-executing explanation of funding sources and trade-offs."""

    proposal_identifier: str
    target_identifier: str
    requested_weight: float
    funded_weight: float
    funding_gap: float
    cash_weight_before: float
    cash_weight_after: float
    funding_sources: tuple[CapitalFundingSource, ...]
    alternative_sources: tuple[str, ...]
    trade_offs: tuple[str, ...]
    summary: str
    policy_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "proposal_identifier",
            "target_identifier",
            "summary",
            "policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "requested_weight",
            "funded_weight",
            "funding_gap",
            "cash_weight_before",
            "cash_weight_after",
        ):
            object.__setattr__(
                self,
                field_name,
                _weight(getattr(self, field_name), field_name=field_name),
            )
        if abs(
            self.requested_weight
            - self.funded_weight
            - self.funding_gap
        ) > 0.0001:
            raise ValueError("funded_weight and funding_gap must reconcile")
        if not isinstance(self.funding_sources, tuple) or not all(
            isinstance(source, CapitalFundingSource)
            for source in self.funding_sources
        ):
            raise TypeError(
                "funding_sources must contain CapitalFundingSource values"
            )

    @property
    def fully_funded(self) -> bool:
        return self.funding_gap == 0.0


def assess_opportunity_cost(
    snapshot: PortfolioSnapshot,
    mandate: PortfolioMandate,
    proposal: PortfolioProposal,
    *,
    funding_candidates: tuple[FundingCandidate, ...] = (),
    policy: OpportunityCostPolicy | None = None,
) -> OpportunityCostAssessment:
    """Explain comparative capital allocation without executing any trade."""

    if not isinstance(snapshot, PortfolioSnapshot):
        raise TypeError("snapshot must be a PortfolioSnapshot")
    if not isinstance(mandate, PortfolioMandate):
        raise TypeError("mandate must be a PortfolioMandate")
    if not isinstance(proposal, PortfolioProposal):
        raise TypeError("proposal must be a PortfolioProposal")
    if proposal.requested_weight_delta <= 0:
        raise ValueError("opportunity-cost funding requires a positive proposal")
    if not isinstance(funding_candidates, tuple) or not all(
        isinstance(candidate, FundingCandidate)
        for candidate in funding_candidates
    ):
        raise TypeError("funding_candidates must contain FundingCandidate values")
    identifiers = [candidate.position_identifier for candidate in funding_candidates]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("funding_candidates cannot contain duplicate positions")

    resolved = policy or OpportunityCostPolicy()
    requested = proposal.requested_weight_delta
    remaining = requested
    sources: list[CapitalFundingSource] = []
    trade_offs: list[str] = []

    excess_cash = max(0.0, snapshot.cash_weight - mandate.minimum_cash_weight)
    if resolved.use_excess_cash_first and excess_cash >= resolved.minimum_material_weight:
        redirected = min(remaining, excess_cash)
        if redirected >= resolved.minimum_material_weight:
            sources.append(
                CapitalFundingSource(
                    identifier="cash-above-reserve",
                    source_type=FundingSourceType.EXCESS_CASH,
                    redirected_weight=redirected,
                    explanation=(
                        f"Redirect {redirected:.1%} from cash above the mandate reserve."
                    ),
                    trade_off=(
                        "The portfolio gives up liquidity, optionality, and cash yield."
                    ),
                )
            )
            trade_offs.append(sources[-1].trade_off)
            remaining = round(remaining - redirected, 6)

    positions = {
        position.identifier: position for position in snapshot.positions
    }
    for candidate in sorted(
        funding_candidates,
        key=lambda item: (item.priority, item.position_identifier),
    ):
        if remaining < resolved.minimum_material_weight:
            break
        position = positions.get(candidate.position_identifier)
        if position is None:
            raise ValueError(
                f"funding candidate is not in the portfolio: {candidate.position_identifier}"
            )
        maximum = min(candidate.maximum_reduction, position.weight)
        redirected = min(remaining, maximum)
        if redirected < resolved.minimum_material_weight:
            continue
        sources.append(
            CapitalFundingSource(
                identifier=position.identifier,
                source_type=FundingSourceType.POSITION_REDUCTION,
                redirected_weight=redirected,
                explanation=(
                    f"Redirect {redirected:.1%} from {position.identifier}: "
                    f"{candidate.reason}"
                ),
                trade_off=candidate.trade_off,
            )
        )
        if candidate.trade_off not in trade_offs:
            trade_offs.append(candidate.trade_off)
        remaining = round(remaining - redirected, 6)

    selected = {source.identifier for source in sources}
    overlapping = snapshot.overlapping_positions(proposal.exposure_tags)
    alternatives = tuple(
        position.identifier
        for position in sorted(
            overlapping,
            key=lambda item: (-item.weight, item.identifier),
        )
        if position.identifier not in selected
    )
    if proposal.estimated_risk_budget_delta > 0:
        trade_offs.append(
            "The portfolio uses more of its risk budget and becomes less resilient "
            "if the new thesis is wrong."
        )

    funded = round(requested - remaining, 6)
    cash_redirected = sum(
        source.redirected_weight
        for source in sources
        if source.source_type is FundingSourceType.EXCESS_CASH
    )
    cash_after = round(snapshot.cash_weight - cash_redirected, 6)
    if remaining < resolved.minimum_material_weight:
        remaining = 0.0
        summary = (
            f"Fund the {requested:.1%} increase in {proposal.target_identifier} "
            f"from {len(sources)} explicit source"
            f"{'s' if len(sources) != 1 else ''}."
        )
    else:
        summary = (
            f"Only {funded:.1%} of the requested {requested:.1%} increase in "
            f"{proposal.target_identifier} is funded. {remaining:.1%} remains "
            "unassigned because the platform will not choose a sale silently."
        )
    return OpportunityCostAssessment(
        proposal_identifier=proposal.identifier,
        target_identifier=proposal.target_identifier,
        requested_weight=requested,
        funded_weight=funded,
        funding_gap=remaining,
        cash_weight_before=snapshot.cash_weight,
        cash_weight_after=cash_after,
        funding_sources=tuple(sources),
        alternative_sources=alternatives,
        trade_offs=tuple(dict.fromkeys(trade_offs)),
        summary=summary,
        policy_version=resolved.version,
    )


def opportunity_cost_to_dict(
    assessment: OpportunityCostAssessment,
) -> dict[str, object]:
    if not isinstance(assessment, OpportunityCostAssessment):
        raise TypeError("assessment must be an OpportunityCostAssessment")
    return {
        "schema_version": "opportunity-cost.v1",
        "proposal_identifier": assessment.proposal_identifier,
        "target_identifier": assessment.target_identifier,
        "requested_weight": assessment.requested_weight,
        "funded_weight": assessment.funded_weight,
        "funding_gap": assessment.funding_gap,
        "fully_funded": assessment.fully_funded,
        "cash": {
            "before": assessment.cash_weight_before,
            "after": assessment.cash_weight_after,
        },
        "funding_sources": [
            {
                "identifier": source.identifier,
                "source_type": source.source_type.value,
                "redirected_weight": source.redirected_weight,
                "explanation": source.explanation,
                "trade_off": source.trade_off,
            }
            for source in assessment.funding_sources
        ],
        "alternative_sources": list(assessment.alternative_sources),
        "trade_offs": list(assessment.trade_offs),
        "summary": assessment.summary,
        "policy_version": assessment.policy_version,
        "non_executing": True,
    }


__all__ = [
    "CapitalFundingSource",
    "FundingCandidate",
    "FundingSourceType",
    "OpportunityCostAssessment",
    "OpportunityCostPolicy",
    "assess_opportunity_cost",
    "opportunity_cost_to_dict",
]
