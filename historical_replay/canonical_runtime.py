"""Production-scale single-pass Canonical CIO historical replay runtime.

The reference canonical adapter is intentionally simple and correct, but reopening and
re-decompressing every historical partition for each cutoff makes a ten-year monthly
run scale as O(cutoffs × archive). This runtime scans the relevant archive once, sorts
by historical availability, and advances a monotonic point-in-time cursor.

A governed no-action outcome is still a decision-process observation. Candidates
rejected before CIO synthesis are therefore preserved separately from true CIO
decisions, while remaining available to the historical-learning resolver through the
backward-compatible ``decisions`` observation collection.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from .canonical import CanonicalHistoricalReplayEngine, ReplayPortfolioState
from .models import HistoricalRecord, iso_timestamp
from .replay import replay_dates

UTC = timezone.utc
_REQUIRED_MACRO_DATASETS = frozenset(
    {
        "series.fedfunds",
        "series.t10y2y",
        "series.vixcls",
    }
)
_SUPPORTIVE_ACTIONS = frozenset({"buy", "increase", "hold", "no_material_change"})
_ABSTENTION_ACTIONS = frozenset(
    {"watch", "insufficient_evidence", "no_superior_opportunity"}
)
_DEFENSIVE_ACTIONS = frozenset({"reduce", "sell", "exit"})
_EVIDENCE_REJECTION_TOKENS = (
    "evidence",
    "coverage",
    "freshness",
    "stale",
    "integrity",
    "data",
    "security master",
    "universe",
)


def _decision_time(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59), tzinfo=UTC)


def _replay_relevant(record: HistoricalRecord) -> bool:
    """Keep only evidence currently consumed by the canonical context builder."""

    return "close" in record.payload or record.dataset in _REQUIRED_MACRO_DATASETS


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip()


class EfficientCanonicalHistoricalReplayEngine(CanonicalHistoricalReplayEngine):
    """Run canonical historical cutoffs from one availability-ordered archive scan."""

    @staticmethod
    def _qualification_action(reasons: tuple[str, ...]) -> str:
        text = " ".join(reasons).lower()
        if any(token in text for token in _EVIDENCE_REJECTION_TOKENS):
            return "insufficient_evidence"
        return "no_superior_opportunity"

    @classmethod
    def _qualification_observation(
        cls,
        qualification: object,
        *,
        candidate: object,
        context: object | None,
    ) -> dict[str, Any]:
        reasons = tuple(str(item) for item in getattr(qualification, "reasons", ()))
        evidence_quality = getattr(candidate, "evidence_quality")
        action = cls._qualification_action(reasons)
        payload: dict[str, Any] = {
            "identifier": (
                "historical-learning-observation:qualification:"
                f"{getattr(qualification, 'candidate_identifier')}"
            ),
            "candidate_identifier": getattr(qualification, "candidate_identifier"),
            "action": action,
            "final_confidence": min(
                float(getattr(evidence_quality, "score", 0.0)),
                float(getattr(evidence_quality, "ceiling", 1.0)),
            ),
            "confidence_source": "qualification_evidence_quality",
            "expected_return": float(getattr(candidate, "net_expected_return")),
            "decision_horizon_days": int(
                getattr(candidate, "decision_horizon_days")
            ),
            "recommended_position_weight": None,
            "funding_source": None,
            "evidence_vetoes": [],
            "implementation_blocks": [],
            "explanation": (
                "The governed opportunity qualification stage rejected the candidate "
                "before specialist/CIO synthesis: " + "; ".join(reasons)
            ),
            "symbol": getattr(getattr(candidate, "instrument"), "symbol"),
            "asset_class": _enum_value(
                getattr(getattr(candidate, "instrument"), "asset_class")
            ),
            "model_versions": list(getattr(candidate, "model_versions", ())),
            "observation_type": "opportunity_qualification",
            "decision_stage": "pre_cio_qualification",
            "canonical_cio_decision": False,
            "qualification_outcome": _enum_value(
                getattr(qualification, "outcome", "rejected")
            ),
            "qualification_policy_version": str(
                getattr(qualification, "policy_version", "unknown")
            ),
            "qualification_reasons": list(reasons),
            "effective_opportunity_cost": float(
                getattr(qualification, "effective_opportunity_cost", 0.0)
            ),
            "opportunity_edge": float(
                getattr(qualification, "opportunity_edge", 0.0)
            ),
            "analysis_lane": _enum_value(
                getattr(qualification, "analysis_lane", "acquisition")
            ),
            "universe_disposition": _enum_value(
                getattr(getattr(qualification, "universe", None), "disposition", "")
            ),
        }
        if context is not None:
            payload.update(
                {
                    "macro_regime": getattr(getattr(context, "macro"), "regime"),
                    "market_regime": getattr(
                        getattr(context, "market"), "market_regime"
                    ),
                }
            )
        return payload

    @staticmethod
    def _mark_cio_observation(payload: dict[str, Any]) -> dict[str, Any]:
        payload.update(
            {
                "observation_type": "cio_decision",
                "decision_stage": "cio_synthesis",
                "canonical_cio_decision": True,
            }
        )
        return payload

    @staticmethod
    def _attach_realized_outcomes(cutoffs: list[dict[str, Any]]) -> None:
        """Attach raw asset returns and decision-relative value to prior observations.

        For supportive actions, decision value follows the asset return. For
        abstention or defensive actions, decision value is the inverse of the asset
        return because avoiding a subsequent loss is beneficial and missing a gain is
        costly. The raw underlying return is always retained separately.
        """

        for index, current in enumerate(cutoffs[:-1]):
            if current.get("state") != "completed":
                continue
            next_completed = next(
                (
                    item
                    for item in cutoffs[index + 1 :]
                    if item.get("state") == "completed"
                ),
                None,
            )
            if next_completed is None:
                continue
            current_prices = dict(current.get("prices") or {})
            next_prices = dict(next_completed.get("prices") or {})
            current_at = datetime.fromisoformat(
                str(current["cutoff"]).replace("Z", "+00:00")
            )
            next_at = datetime.fromisoformat(
                str(next_completed["cutoff"]).replace("Z", "+00:00")
            )
            horizon_days = max(1, (next_at - current_at).days)
            for observation in current.get("decisions", []):
                if not isinstance(observation, dict):
                    continue
                symbol = str(observation.get("symbol") or "").upper()
                current_price = current_prices.get(symbol)
                next_price = next_prices.get(symbol)
                if not isinstance(current_price, (int, float)) or not isinstance(
                    next_price, (int, float)
                ):
                    continue
                if float(current_price) <= 0.0:
                    continue
                underlying_return = round(
                    float(next_price) / float(current_price) - 1.0,
                    8,
                )
                action = str(observation.get("action") or "").strip().lower()
                if action in _ABSTENTION_ACTIONS or action in _DEFENSIVE_ACTIONS:
                    decision_value = round(-underlying_return, 8)
                    outcome = (
                        "avoided_loss"
                        if underlying_return < 0.0
                        else "missed_opportunity"
                        if underlying_return > 0.0
                        else "neutral_abstention"
                    )
                else:
                    decision_value = underlying_return
                    outcome = (
                        "supported_gain"
                        if underlying_return > 0.0
                        else "supported_loss"
                        if underlying_return < 0.0
                        else "neutral_support"
                    )
                observation["underlying_return_to_next_cutoff"] = underlying_return
                observation["realized_return_to_next_cutoff"] = decision_value
                observation["realized_decision_value_to_next_cutoff"] = decision_value
                observation["realized_outcome"] = outcome
                observation["realized_horizon_days"] = horizon_days

    def run(
        self,
        *,
        start: date,
        end: date,
        cadence: str = "monthly",
        strict_only: bool = False,
        initial_portfolio_value: float = 250_000.0,
    ) -> dict[str, Any]:
        if initial_portfolio_value <= 0.0:
            raise ValueError("initial_portfolio_value must be positive")
        if start > end:
            raise ValueError("start must not be after end")

        relevant = sorted(
            (
                record
                for record in self.store.iter_records(strict_only=strict_only)
                if _replay_relevant(record)
            ),
            key=lambda item: (item.available_datetime, item.record_id),
        )
        price_record_count = sum(1 for item in relevant if "close" in item.payload)
        macro_record_count = len(relevant) - price_record_count

        state = ReplayPortfolioState(value=float(initial_portfolio_value))
        decisions: list[dict[str, Any]] = []
        completed = blocked = 0
        visible: list[HistoricalRecord] = []
        cursor = 0

        for cutoff_date in replay_dates(start, end, cadence):
            cutoff = _decision_time(cutoff_date)
            while (
                cursor < len(relevant)
                and relevant[cursor].available_datetime <= cutoff
            ):
                visible.append(relevant[cursor])
                cursor += 1
            records = tuple(visible)
            try:
                candidates, contexts, opportunity, portfolio, prices = (
                    self.builder.build(
                        records=records,
                        cutoff=cutoff,
                        state=state,
                        strict_only=strict_only,
                    )
                )
                if not candidates:
                    raise RuntimeError(
                        "no historical candidates satisfy the point-in-time coverage gate"
                    )
                result = self.cycle.run(
                    identifier=f"historical-canonical-cycle:{cutoff_date}",
                    candidates=candidates,
                    opportunity_context=opportunity,
                    specialist_contexts=contexts,
                    portfolio=portfolio,
                    code_version="historical-canonical-replay.v3",
                )
                candidate_map = {item.identifier: item for item in candidates}
                context_map = {
                    item.candidate_identifier: item for item in contexts
                }
                cio_decision_payloads = [
                    self._mark_cio_observation(
                        self._decision_payload(
                            item,
                            candidate=candidate_map.get(item.candidate_identifier),
                            context=context_map.get(item.candidate_identifier),
                        )
                    )
                    for item in result.decisions
                ]
                rejection_payloads = [
                    self._qualification_observation(
                        item,
                        candidate=candidate_map[item.candidate_identifier],
                        context=context_map.get(item.candidate_identifier),
                    )
                    for item in result.opportunity_queue.rejected
                    if item.candidate_identifier in candidate_map
                ]
                learning_observations = cio_decision_payloads + rejection_payloads
                state.apply_construction(result.construction)
                state.previous_prices.update(prices)
                construction = result.construction
                payload = {
                    "cutoff": iso_timestamp(cutoff),
                    "state": "completed",
                    "canonical_cio_invoked": True,
                    "candidate_count": len(candidates),
                    "decision_count": len(result.decisions),
                    "qualification_rejection_count": len(rejection_payloads),
                    "learning_observation_count": len(learning_observations),
                    "visible_record_count": len(records),
                    # Backward-compatible field consumed by HistoricalLearningResolver.
                    "decisions": learning_observations,
                    "cio_decisions": cio_decision_payloads,
                    "qualification_observations": rejection_payloads,
                    "prices": dict(prices),
                    "macro_regime": (
                        contexts[0].macro.regime if contexts else "unavailable"
                    ),
                    "construction": (
                        None
                        if construction is None
                        else {
                            "status": construction.status.value,
                            "target_cash_weight": construction.target_cash_weight,
                            "target_weights": dict(construction.target_weights),
                            "turnover": construction.turnover,
                            "estimated_cost_return": construction.estimated_cost_return,
                            "blocks": list(construction.blocks),
                        }
                    ),
                    "portfolio_value": state.value,
                    "portfolio_weights": dict(state.weights),
                    "cash_weight": state.cash_weight,
                }
                completed += 1
            except Exception as error:
                payload = {
                    "cutoff": iso_timestamp(cutoff),
                    "state": "blocked",
                    "canonical_cio_invoked": False,
                    "visible_record_count": len(records),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "portfolio_value": state.value,
                    "portfolio_weights": dict(state.weights),
                    "cash_weight": state.cash_weight,
                }
                blocked += 1
            decisions.append(payload)

        self._attach_realized_outcomes(decisions)
        all_observations = [
            observation
            for cutoff in decisions
            for observation in cutoff.get("decisions", [])
            if isinstance(observation, dict)
        ]
        realized_outcome_count = sum(
            isinstance(observation.get("realized_return_to_next_cutoff"), (int, float))
            for observation in all_observations
        )
        qualification_observation_count = sum(
            observation.get("decision_stage") == "pre_cio_qualification"
            for observation in all_observations
        )
        cio_decision_observation_count = sum(
            observation.get("canonical_cio_decision") is True
            for observation in all_observations
        )
        avoided_loss_count = sum(
            observation.get("realized_outcome") == "avoided_loss"
            for observation in all_observations
        )
        missed_opportunity_count = sum(
            observation.get("realized_outcome") == "missed_opportunity"
            for observation in all_observations
        )
        report = {
            "schema_version": "canonical-historical-replay.v3",
            "runtime_version": "single-pass-availability-cursor.v3",
            "learning_context_schema_version": "governed-historical-learning.v1",
            "generated_at": iso_timestamp(datetime.now(tz=UTC)),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "cadence": cadence,
            "strict_only": strict_only,
            "strict_replay": strict_only,
            "research_only": True,
            "canonical_cio_available": True,
            "canonical_cio_invoked_count": completed,
            "blocked_cutoff_count": blocked,
            "decision_cutoff_count": len(decisions),
            "archive_scan_count": 1,
            "relevant_record_count": len(relevant),
            "price_record_count": price_record_count,
            "macro_record_count": macro_record_count,
            "learning_observation_count": len(all_observations),
            "cio_decision_observation_count": cio_decision_observation_count,
            "qualification_observation_count": qualification_observation_count,
            "realized_outcome_count": realized_outcome_count,
            "avoided_loss_count": avoided_loss_count,
            "missed_opportunity_count": missed_opportunity_count,
            "initial_portfolio_value": float(initial_portfolio_value),
            "ending_portfolio_value": state.value,
            "ending_weights": dict(state.weights),
            "ending_cash_weight": state.cash_weight,
            "decisions": decisions,
            "execution_authorized": False,
            "paper_execution_authorized": False,
            "real_money_authorized": False,
            "policy_promotion_authorized": False,
            "performance_claims_authorized": False,
        }
        self.store.write_manifest("latest-canonical-replay", report)
        return report


__all__ = ["EfficientCanonicalHistoricalReplayEngine"]
