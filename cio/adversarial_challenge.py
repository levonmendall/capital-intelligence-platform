"""Non-voting adversarial challenge and pre-mortem for material CIO conclusions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ProposedAction(str, Enum):
    BUY = "BUY"
    INCREASE = "INCREASE"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    CASH = "CASH"


@dataclass(frozen=True, slots=True)
class DecisionProposal:
    identifier: str
    as_of: datetime
    action: ProposedAction
    rationale: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    opposing_evidence: tuple[str, ...]
    hidden_assumptions: tuple[str, ...]
    cash_case_evidence: tuple[str, ...]
    replacement_evidence: tuple[str, ...]
    tail_risks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.rationale:
            raise ValueError("proposal identifier and rationale are required")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ChallengePackage:
    proposal_identifier: str
    strongest_case_for: str
    strongest_case_against: str
    strongest_case_for_cash: str
    superior_replacement_argument: str
    hidden_assumptions: tuple[str, ...]
    likely_value_trap: str
    likely_timing_error: str
    market_information_advantage: str
    most_dangerous_tail: str
    pre_mortem: str
    reversal_evidence: tuple[str, ...]
    evidence_cutoff: datetime
    schema_version: str = "adversarial-challenge.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            **{name: getattr(self, name) for name in (
                "proposal_identifier", "strongest_case_for", "strongest_case_against",
                "strongest_case_for_cash", "superior_replacement_argument",
                "likely_value_trap", "likely_timing_error", "market_information_advantage",
                "most_dangerous_tail", "pre_mortem", "schema_version"
            )},
            "hidden_assumptions": list(self.hidden_assumptions),
            "reversal_evidence": list(self.reversal_evidence),
            "evidence_cutoff": self.evidence_cutoff.isoformat(),
            "voting_authority": False,
            "veto_authority": False,
            "trade_authority": False,
        }


class AdversarialCIOChallengeEngine:
    version = "adversarial-cio-challenge.v1"

    @staticmethod
    def _strongest(values: tuple[str, ...], fallback: str) -> str:
        return max(values, key=lambda value: (len(value), value)) if values else fallback

    def challenge(self, proposal: DecisionProposal) -> ChallengePackage:
        strongest_for = self._strongest(proposal.supporting_evidence, proposal.rationale[0])
        strongest_against = self._strongest(
            proposal.opposing_evidence,
            "No evidence-backed opposing case was supplied; the challenge remains incomplete.",
        )
        cash_case = self._strongest(
            proposal.cash_case_evidence,
            "Cash is superior only if the proposed edge does not survive costs and downside.",
        )
        replacement = self._strongest(
            proposal.replacement_evidence,
            "No evidence-backed superior replacement was supplied.",
        )
        tail = self._strongest(
            proposal.tail_risks,
            "No supported tail risk was supplied; do not invent one merely for symmetry.",
        )
        if proposal.action in {ProposedAction.BUY, ProposedAction.INCREASE}:
            pre_mortem = f"Assume the investment loses 30%. The most likely misunderstanding was: {strongest_against}"
        elif proposal.action is ProposedAction.CASH:
            pre_mortem = "Assume markets rise substantially while cash persists. Review whether a rejection, evidence gap, or construction mechanism caused the opportunity loss."
        elif proposal.action is ProposedAction.HOLD:
            pre_mortem = "Assume the HOLD underperforms. Test whether the thesis remained attractive or anchoring preserved the position."
        else:
            pre_mortem = f"Assume the action fails. Re-examine: {strongest_against}"
        return ChallengePackage(
            proposal_identifier=proposal.identifier,
            strongest_case_for=strongest_for,
            strongest_case_against=strongest_against,
            strongest_case_for_cash=cash_case,
            superior_replacement_argument=replacement,
            hidden_assumptions=proposal.hidden_assumptions,
            likely_value_trap=strongest_against,
            likely_timing_error=self._strongest(proposal.opposing_evidence, "Timing error unresolved."),
            market_information_advantage="The market may reflect information absent from the frozen evidence package; require observable reversal evidence rather than assuming informational superiority.",
            most_dangerous_tail=tail,
            pre_mortem=pre_mortem,
            reversal_evidence=tuple(dict.fromkeys((*proposal.opposing_evidence, *proposal.tail_risks))),
            evidence_cutoff=proposal.as_of,
        )
