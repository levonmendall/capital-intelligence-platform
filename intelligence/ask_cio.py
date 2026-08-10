"""Read-only, source-grounded Ask the CIO retrieval service.

The service answers natural-language questions from persisted Decision Intelligence v3
packets. It is deliberately non-agentic: it cannot create a candidate, alter a CIO
conclusion, change policy, construct a portfolio, or execute. A future language-model
presentation layer may paraphrase this response only if it preserves the returned
claims, timestamps, limitations, and source lineage.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.decision_intelligence_v3 import SQLiteDecisionIntelligenceV3Store


@dataclass(frozen=True, slots=True)
class AskCIOAnswer:
    question: str
    intent: str
    as_of: datetime | None
    answer: str
    claims: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]
    read_only: bool = True
    investment_authority: bool = False
    construction_authority: bool = False
    execution_authority: bool = False
    schema_version: str = "ask-cio-answer.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
            "as_of": None if self.as_of is None else self.as_of.isoformat(),
            "answer": self.answer,
            "claims": list(self.claims),
            "evidence_identifiers": list(self.evidence_identifiers),
            "limitations": list(self.limitations),
            "read_only": True,
            "investment_authority": False,
            "construction_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def _db_path() -> Path:
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_DECISION_INTELLIGENCE_V3_DB",
            "database/decision-intelligence-v3.db",
        )
    ).expanduser()


def _as_of(packet: dict[str, Any] | None) -> datetime | None:
    if packet is None:
        return None
    raw = packet.get("as_of")
    if not isinstance(raw, str):
        return None
    return datetime.fromisoformat(raw)


def _source_ids(packet: dict[str, Any]) -> tuple[str, ...]:
    ids = []
    ids.extend(str(item) for item in packet.get("source_lineage", ()) if str(item).strip())
    explanation = packet.get("explanation")
    if isinstance(explanation, dict):
        ids.extend(
            str(item)
            for item in explanation.get("evidence_identifiers", ())
            if str(item).strip()
        )
    return tuple(dict.fromkeys(ids))


def _candidate_from_question(question: str, packets: tuple[dict[str, Any], ...]):
    upper = question.upper()
    for packet in packets:
        symbol = str(packet.get("symbol", "")).strip().upper()
        name = str(packet.get("name", "")).strip().lower()
        if symbol and re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", upper):
            return packet
        if name and len(name) >= 4 and name in question.lower():
            return packet
    return None


class AskCIOService:
    version = "ask-cio-read-model.v1"

    def __init__(self, store: SQLiteDecisionIntelligenceV3Store | None = None) -> None:
        self.store = store or SQLiteDecisionIntelligenceV3Store(_db_path())

    def answer(self, question: str) -> AskCIOAnswer:
        normalized = str(question).strip()
        if not normalized:
            raise ValueError("question cannot be empty")
        packets = self.store.latest_cycle_packets()
        if not packets:
            return AskCIOAnswer(
                question=normalized,
                intent="no_data",
                as_of=None,
                answer="No governed Decision Intelligence v3 packet has been recorded yet.",
                claims=(),
                evidence_identifiers=(),
                limitations=("A completed production CIO cycle is required before this read model can answer.",),
            )

        lower = normalized.lower()
        candidate = _candidate_from_question(normalized, packets)
        if candidate is not None:
            return self._candidate_answer(normalized, lower, candidate)
        if "cash" in lower or "why are we holding" in lower:
            return self._cash_answer(normalized, packets)
        if any(token in lower for token in ("best opportunity", "strongest opportunity", "best investment", "next dollar")):
            return self._best_opportunity_answer(normalized, packets)
        if any(token in lower for token in ("what changed", "changed today", "why does it matter")):
            return self._changed_answer(normalized, packets)
        return self._cycle_summary(normalized, packets)

    def _candidate_answer(self, question: str, lower: str, packet: dict[str, Any]) -> AskCIOAnswer:
        opportunity = dict(packet.get("opportunity", {}))
        objective = dict(packet.get("objective", {}))
        explanation = dict(packet.get("explanation", {}))
        symbol = str(packet.get("symbol", "candidate"))
        action = str(packet.get("cio_action", "unknown"))
        target = float(opportunity.get("proposed_target_weight", 0.0))
        current = float(opportunity.get("current_weight", 0.0))
        dollar = float(opportunity.get("expected_dollar_value_added", 0.0))
        edge_cash = float(opportunity.get("edge_over_cash", 0.0))
        edge_alt = float(opportunity.get("edge_over_best_alternative", 0.0))
        claims = [
            f"CIO action for {symbol}: {action}.",
            f"Current weight {current:.2%}; construction target {target:.2%}.",
            f"Expected candidate edge over cash {edge_cash:+.2%} and over the best governed alternative {edge_alt:+.2%}.",
            f"Expected portfolio dollar-value improvement recorded by construction: ${dollar:,.2f}.",
        ]
        if "expect" in lower or "priced" in lower:
            claims.extend(
                (
                    f"Market expectation: {explanation.get('market_expectation', 'unavailable')}.",
                    f"Internal expectation: {explanation.get('internal_expectation', 'unavailable')}.",
                    f"Expected surprise: {explanation.get('expected_surprise')}.",
                    f"Priced-in score: {explanation.get('priced_in_score')}.",
                )
            )
        if "risk" in lower or "downside" in lower:
            claims.extend(str(item) for item in packet.get("risk_summary", ()))
        reasons = tuple(str(item) for item in packet.get("cio_rationale", ()) if str(item).strip())
        claims.extend(reasons)
        answer = " ".join(claims)
        return AskCIOAnswer(
            question=question,
            intent="candidate_decision",
            as_of=_as_of(packet),
            answer=answer,
            claims=tuple(dict.fromkeys(claims)),
            evidence_identifiers=_source_ids(packet),
            limitations=(
                "This answer is a read-only reconstruction of the governed CIO packet; it cannot change the portfolio.",
                f"Expected terminal portfolio value in the recorded decision horizon was ${float(objective.get('expected_terminal_portfolio_value', 0.0)):,.2f}; this is an expectation, not a guaranteed outcome.",
            ),
        )

    def _cash_answer(self, question: str, packets: tuple[dict[str, Any], ...]) -> AskCIOAnswer:
        first = packets[0]
        objective = dict(first.get("objective", {}))
        cash_weight = float(objective.get("cash_weight", 0.0))
        cash_return = float(objective.get("cash_expected_return", 0.0))
        changes = [packet for packet in packets if dict(packet.get("opportunity", {})).get("changes_portfolio")]
        no_change_reasons = []
        for packet in packets:
            if not dict(packet.get("opportunity", {})).get("changes_portfolio"):
                no_change_reasons.extend(str(item) for item in packet.get("cio_rationale", ()) if str(item).strip())
        claims = (
            f"Cash weight at the latest CIO decision was {cash_weight:.2%}.",
            f"The governed cash expected-return hurdle was {cash_return:.2%}.",
            f"{len(changes)} candidate decision(s) changed the constructed portfolio in the latest cycle.",
            *tuple(dict.fromkeys(no_change_reasons))[:5],
        )
        ids = tuple(dict.fromkeys(identifier for packet in packets for identifier in _source_ids(packet)))
        return AskCIOAnswer(
            question=question,
            intent="cash_rationale",
            as_of=_as_of(first),
            answer=" ".join(claims),
            claims=claims,
            evidence_identifiers=ids,
            limitations=("Cash remains a competing use of capital; this read model does not lower the hurdle to force investment.",),
        )

    def _best_opportunity_answer(self, question: str, packets: tuple[dict[str, Any], ...]) -> AskCIOAnswer:
        best = max(
            packets,
            key=lambda packet: float(dict(packet.get("opportunity", {})).get("expected_dollar_value_added", 0.0)),
        )
        opportunity = dict(best.get("opportunity", {}))
        claims = (
            f"Highest recorded expected dollar-value contribution in the latest CIO cycle: {best.get('symbol')}.",
            f"Expected dollar-value improvement: ${float(opportunity.get('expected_dollar_value_added', 0.0)):,.2f}.",
            f"Marginal portfolio return improvement: {float(opportunity.get('marginal_portfolio_improvement', 0.0)):+.2%}.",
            f"CIO action: {best.get('cio_action')}.",
        )
        return AskCIOAnswer(
            question=question,
            intent="best_opportunity",
            as_of=_as_of(best),
            answer=" ".join(claims),
            claims=claims,
            evidence_identifiers=_source_ids(best),
            limitations=("Ranking reflects the latest completed governed CIO cycle, not an intracycle trade signal.",),
        )

    def _changed_answer(self, question: str, packets: tuple[dict[str, Any], ...]) -> AskCIOAnswer:
        claims = []
        ids = []
        for packet in packets[:5]:
            explanation = dict(packet.get("explanation", {}))
            changed = tuple(str(item) for item in explanation.get("what_changed", ()) if str(item).strip())
            if changed:
                claims.append(f"{packet.get('symbol')}: " + " | ".join(changed[:3]))
                ids.extend(_source_ids(packet))
        if not claims:
            claims.append("No material candidate-level change narrative was recorded in the latest CIO packets.")
        return AskCIOAnswer(
            question=question,
            intent="what_changed",
            as_of=_as_of(packets[0]),
            answer=" ".join(claims),
            claims=tuple(claims),
            evidence_identifiers=tuple(dict.fromkeys(ids)),
            limitations=("The answer reports information that reached the governed CIO context; it is not a general news feed.",),
        )

    def _cycle_summary(self, question: str, packets: tuple[dict[str, Any], ...]) -> AskCIOAnswer:
        changed = [packet for packet in packets if dict(packet.get("opportunity", {})).get("changes_portfolio")]
        expected_dollars = sum(float(dict(packet.get("opportunity", {})).get("expected_dollar_value_added", 0.0)) for packet in changed)
        claims = (
            f"The latest CIO cycle recorded {len(packets)} candidate decision packet(s).",
            f"{len(changed)} changed the constructed portfolio.",
            f"Summed candidate-level expected dollar-value contribution diagnostics for changed decisions: ${expected_dollars:,.2f}.",
            "One governed CIO remains the sole investment authority; this conversational surface is read-only.",
        )
        ids = tuple(dict.fromkeys(identifier for packet in packets for identifier in _source_ids(packet)))
        return AskCIOAnswer(
            question=question,
            intent="cycle_summary",
            as_of=_as_of(packets[0]),
            answer=" ".join(claims),
            claims=claims,
            evidence_identifiers=ids,
            limitations=("Ask a security symbol, cash rationale, expectations, risk, what changed, or the best opportunity for a more specific answer.",),
        )


__all__ = ["AskCIOAnswer", "AskCIOService"]
