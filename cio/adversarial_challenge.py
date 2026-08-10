"""Non-voting adversarial challenge and pre-mortem for material CIO conclusions.

The challenge engine is deliberately advisory.  It can expose counterarguments,
hidden assumptions, cash/replacement cases, timing errors, and tail risks, but it
cannot qualify or remove a candidate, change a position size, issue a trade, or veto
a CIO action.
"""

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
class CommitteeChallengeProposal:
    """Pre-CIO research thesis supplied after the six independent specialists.

    Unlike :class:`DecisionProposal`, this object has no proposed action.  That is an
    intentional governance boundary: the Red Team challenges the evidence package
    before the CIO decides, but cannot manufacture a BUY/HOLD/EXIT recommendation.
    """

    identifier: str
    as_of: datetime
    rationale: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    opposing_evidence: tuple[str, ...]
    hidden_assumptions: tuple[str, ...]
    cash_case_evidence: tuple[str, ...]
    replacement_evidence: tuple[str, ...]
    tail_risks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("proposal identifier is required")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.rationale, tuple) or not self.rationale:
            raise ValueError("committee challenge requires a rationale")
        for field_name in (
            "rationale",
            "supporting_evidence",
            "opposing_evidence",
            "hidden_assumptions",
            "cash_case_evidence",
            "replacement_evidence",
            "tail_risks",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")


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
            **{
                name: getattr(self, name)
                for name in (
                    "proposal_identifier",
                    "strongest_case_for",
                    "strongest_case_against",
                    "strongest_case_for_cash",
                    "superior_replacement_argument",
                    "likely_value_trap",
                    "likely_timing_error",
                    "market_information_advantage",
                    "most_dangerous_tail",
                    "pre_mortem",
                    "schema_version",
                )
            },
            "hidden_assumptions": list(self.hidden_assumptions),
            "reversal_evidence": list(self.reversal_evidence),
            "evidence_cutoff": self.evidence_cutoff.isoformat(),
            "voting_authority": False,
            "veto_authority": False,
            "trade_authority": False,
            "candidate_qualification_authority": False,
            "position_sizing_authority": False,
        }


class AdversarialCIOChallengeEngine:
    version = "adversarial-cio-challenge.v2-pre-cio"

    @staticmethod
    def _strongest(values: tuple[str, ...], fallback: str) -> str:
        return max(values, key=lambda value: (len(value), value)) if values else fallback

    def _package(
        self,
        *,
        identifier: str,
        as_of: datetime,
        rationale: tuple[str, ...],
        supporting_evidence: tuple[str, ...],
        opposing_evidence: tuple[str, ...],
        hidden_assumptions: tuple[str, ...],
        cash_case_evidence: tuple[str, ...],
        replacement_evidence: tuple[str, ...],
        tail_risks: tuple[str, ...],
        pre_mortem: str,
    ) -> ChallengePackage:
        strongest_for = self._strongest(supporting_evidence, rationale[0])
        strongest_against = self._strongest(
            opposing_evidence,
            "No evidence-backed opposing case was supplied; the challenge remains incomplete.",
        )
        cash_case = self._strongest(
            cash_case_evidence,
            "Cash is superior only if the proposed edge does not survive costs and downside.",
        )
        replacement = self._strongest(
            replacement_evidence,
            "No evidence-backed superior replacement was supplied.",
        )
        tail = self._strongest(
            tail_risks,
            "No supported tail risk was supplied; do not invent one merely for symmetry.",
        )
        return ChallengePackage(
            proposal_identifier=identifier,
            strongest_case_for=strongest_for,
            strongest_case_against=strongest_against,
            strongest_case_for_cash=cash_case,
            superior_replacement_argument=replacement,
            hidden_assumptions=hidden_assumptions,
            likely_value_trap=strongest_against,
            likely_timing_error=self._strongest(
                opposing_evidence,
                "Timing error unresolved.",
            ),
            market_information_advantage=(
                "The market may reflect information absent from the frozen evidence package; "
                "require observable reversal evidence rather than assuming informational superiority."
            ),
            most_dangerous_tail=tail,
            pre_mortem=pre_mortem,
            reversal_evidence=tuple(
                dict.fromkeys((*opposing_evidence, *tail_risks))
            ),
            evidence_cutoff=as_of,
        )

    def challenge(self, proposal: DecisionProposal) -> ChallengePackage:
        strongest_against = self._strongest(
            proposal.opposing_evidence,
            "No evidence-backed opposing case was supplied; the challenge remains incomplete.",
        )
        if proposal.action in {ProposedAction.BUY, ProposedAction.INCREASE}:
            pre_mortem = (
                "Assume the investment loses 30%. The most likely misunderstanding was: "
                + strongest_against
            )
        elif proposal.action is ProposedAction.CASH:
            pre_mortem = (
                "Assume markets rise substantially while cash persists. Review whether a "
                "rejection, evidence gap, or construction mechanism caused the opportunity loss."
            )
        elif proposal.action is ProposedAction.HOLD:
            pre_mortem = (
                "Assume the HOLD underperforms. Test whether the thesis remained attractive "
                "or anchoring preserved the position."
            )
        else:
            pre_mortem = f"Assume the action fails. Re-examine: {strongest_against}"
        return self._package(
            identifier=proposal.identifier,
            as_of=proposal.as_of,
            rationale=proposal.rationale,
            supporting_evidence=proposal.supporting_evidence,
            opposing_evidence=proposal.opposing_evidence,
            hidden_assumptions=proposal.hidden_assumptions,
            cash_case_evidence=proposal.cash_case_evidence,
            replacement_evidence=proposal.replacement_evidence,
            tail_risks=proposal.tail_risks,
            pre_mortem=pre_mortem,
        )

    def challenge_committee(
        self,
        proposal: CommitteeChallengeProposal,
    ) -> ChallengePackage:
        """Challenge a completed committee packet before any CIO action exists."""

        strongest_against = self._strongest(
            proposal.opposing_evidence,
            "No evidence-backed opposing case was supplied; actively monitor for evidence the committee missed.",
        )
        pre_mortem = (
            "Assume the candidate materially underperforms after CIO review. The strongest "
            "pre-decision explanation to re-test is: "
            + strongest_against
        )
        return self._package(
            identifier=proposal.identifier,
            as_of=proposal.as_of,
            rationale=proposal.rationale,
            supporting_evidence=proposal.supporting_evidence,
            opposing_evidence=proposal.opposing_evidence,
            hidden_assumptions=proposal.hidden_assumptions,
            cash_case_evidence=proposal.cash_case_evidence,
            replacement_evidence=proposal.replacement_evidence,
            tail_risks=proposal.tail_risks,
            pre_mortem=pre_mortem,
        )


__all__ = [
    "AdversarialCIOChallengeEngine",
    "ChallengePackage",
    "CommitteeChallengeProposal",
    "DecisionProposal",
    "ProposedAction",
]
