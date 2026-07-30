"""Horizon-aligned governed learning over the single-pass canonical replay.

This layer preserves the production Canonical CIO replay while separating policy-only
abstentions from decision calibration and evaluating outcomes at each observation's
stated decision horizon. The complete replay remains research-only and no execution or
policy-promotion authority is introduced.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .canonical_runtime import EfficientCanonicalHistoricalReplayEngine

UTC = timezone.utc
_ABSTENTION_ACTIONS = frozenset(
    {"watch", "insufficient_evidence", "no_superior_opportunity"}
)
_DEFENSIVE_ACTIONS = frozenset({"reduce", "sell", "exit"})
_CAPABILITY_POLICY_TOKENS = (
    "intelligence-only because its market or economic exposure lacks a configured capability authority",
    "lacks a configured capability authority",
    "outside the configured capability authority",
    "not authorized by the configured capability authority",
)


def _cutoff_time(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("cutoff")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _decision_value(action: str, underlying_return: float) -> tuple[float, str]:
    if action in _ABSTENTION_ACTIONS or action in _DEFENSIVE_ACTIONS:
        value = round(-underlying_return, 8)
        outcome = (
            "avoided_loss"
            if underlying_return < 0.0
            else "missed_opportunity"
            if underlying_return > 0.0
            else "neutral_abstention"
        )
        return value, outcome
    value = round(underlying_return, 8)
    outcome = (
        "supported_gain"
        if underlying_return > 0.0
        else "supported_loss"
        if underlying_return < 0.0
        else "neutral_support"
    )
    return value, outcome


class HorizonAlignedCanonicalHistoricalReplayEngine(
    EfficientCanonicalHistoricalReplayEngine
):
    """Produce a calibration-safe v4 manifest from the single-pass replay."""

    @staticmethod
    def _governance_only_rejection(reasons: tuple[str, ...]) -> bool:
        if not reasons:
            return False
        return all(
            any(token in reason.lower() for token in _CAPABILITY_POLICY_TOKENS)
            for reason in reasons
        )

    @classmethod
    def _qualification_observation(
        cls,
        qualification: object,
        *,
        candidate: object,
        context: object | None,
    ) -> dict[str, Any]:
        payload = super()._qualification_observation(
            qualification,
            candidate=candidate,
            context=context,
        )
        reasons = tuple(str(item) for item in payload.get("qualification_reasons", ()))
        governance_only = cls._governance_only_rejection(reasons)
        payload.update(
            {
                "learning_scope": (
                    "governance_only" if governance_only else "decision_calibration"
                ),
                "calibration_eligible": not governance_only,
            }
        )
        return payload

    @staticmethod
    def _mark_cio_observation(payload: dict[str, Any]) -> dict[str, Any]:
        payload = EfficientCanonicalHistoricalReplayEngine._mark_cio_observation(
            payload
        )
        payload.update(
            {
                "learning_scope": "decision_calibration",
                "calibration_eligible": True,
            }
        )
        return payload

    @staticmethod
    def _future_price_cutoff(
        cutoffs: list[dict[str, Any]],
        *,
        start_index: int,
        symbol: str,
        not_before: datetime,
        maximum_slippage_days: int,
    ) -> tuple[datetime, float] | None:
        for item in cutoffs[start_index:]:
            if item.get("state") != "completed":
                continue
            cutoff_at = _cutoff_time(item)
            if cutoff_at is None or cutoff_at < not_before:
                continue
            if (cutoff_at - not_before).days > maximum_slippage_days:
                return None
            prices = item.get("prices")
            if not isinstance(prices, dict):
                continue
            price = prices.get(symbol)
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                continue
            if float(price) <= 0.0:
                continue
            return cutoff_at, float(price)
        return None

    @classmethod
    def _attach_realized_outcomes(cls, cutoffs: list[dict[str, Any]]) -> None:
        # Preserve next-cutoff monitoring evidence from the v3 engine.
        EfficientCanonicalHistoricalReplayEngine._attach_realized_outcomes(cutoffs)
        for current in cutoffs:
            for observation in current.get("decisions", []):
                if not isinstance(observation, dict):
                    continue
                if "realized_horizon_days" in observation:
                    observation["next_cutoff_horizon_days"] = observation.pop(
                        "realized_horizon_days"
                    )
                if "realized_outcome" in observation:
                    observation["next_cutoff_outcome"] = observation.pop(
                        "realized_outcome"
                    )

        # Add outcome evidence at the stated decision horizon.
        for index, current in enumerate(cutoffs[:-1]):
            if current.get("state") != "completed":
                continue
            current_at = _cutoff_time(current)
            prices = current.get("prices")
            if current_at is None or not isinstance(prices, dict):
                continue
            for observation in current.get("decisions", []):
                if not isinstance(observation, dict):
                    continue
                symbol = str(observation.get("symbol") or "").strip().upper()
                current_price = prices.get(symbol)
                requested_horizon = observation.get("decision_horizon_days")
                if (
                    not symbol
                    or isinstance(current_price, bool)
                    or not isinstance(current_price, (int, float))
                    or float(current_price) <= 0.0
                    or isinstance(requested_horizon, bool)
                    or not isinstance(requested_horizon, (int, float))
                    or float(requested_horizon) <= 0.0
                ):
                    continue
                target_days = max(1, int(round(float(requested_horizon))))
                target_at = current_at + timedelta(days=target_days)
                maximum_slippage = max(45, int(round(target_days * 0.15)))
                match = cls._future_price_cutoff(
                    cutoffs,
                    start_index=index + 1,
                    symbol=symbol,
                    not_before=target_at,
                    maximum_slippage_days=maximum_slippage,
                )
                if match is None:
                    continue
                horizon_at, horizon_price = match
                underlying_return = round(
                    horizon_price / float(current_price) - 1.0,
                    8,
                )
                action = str(observation.get("action") or "").strip().lower()
                decision_value, outcome = _decision_value(action, underlying_return)
                observation.update(
                    {
                        "underlying_return_at_decision_horizon": underlying_return,
                        "realized_return_at_decision_horizon": decision_value,
                        "realized_decision_value_at_horizon": decision_value,
                        "realized_outcome": outcome,
                        "realized_horizon_days": max(
                            1, (horizon_at - current_at).days
                        ),
                        "realized_horizon_target_days": target_days,
                    }
                )

    @staticmethod
    def _learning_input_report(report: dict[str, Any]) -> dict[str, Any]:
        cutoffs: list[dict[str, Any]] = []
        bounded_count = 0
        for raw_cutoff in report.get("decisions", []):
            if not isinstance(raw_cutoff, dict):
                continue
            cutoff = dict(raw_cutoff)
            observations: list[dict[str, Any]] = []
            for raw_observation in raw_cutoff.get("decisions", []):
                if not isinstance(raw_observation, dict):
                    continue
                if raw_observation.get("calibration_eligible") is False:
                    continue
                observation = dict(raw_observation)
                # The base resolver consumes this legacy field. It is deliberately
                # remapped to the decision-horizon value, never the next cutoff.
                observation.pop("realized_return_to_next_cutoff", None)
                value = observation.get("realized_decision_value_at_horizon")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    raw_value = float(value)
                    # A missed-opportunity regret can be below -100% when the avoided
                    # asset more than doubles. The raw value remains in the protected
                    # replay, while the live calibration contract is bounded to the
                    # return domain accepted by HistoricalLearningContext.
                    bounded_value = max(-1.0, raw_value)
                    was_bounded = bounded_value != raw_value
                    bounded_count += was_bounded
                    observation["calibration_return_at_horizon"] = bounded_value
                    observation["calibration_return_was_bounded"] = was_bounded
                    observation["realized_return_to_next_cutoff"] = bounded_value
                observations.append(observation)
            cutoff["decisions"] = observations
            cutoff["learning_observation_count"] = len(observations)
            cutoffs.append(cutoff)

        eligible = [
            observation
            for cutoff in cutoffs
            for observation in cutoff.get("decisions", [])
            if isinstance(observation, dict)
        ]
        horizon_count = sum(
            isinstance(
                observation.get("realized_decision_value_at_horizon"),
                (int, float),
            )
            and not isinstance(
                observation.get("realized_decision_value_at_horizon"), bool
            )
            for observation in eligible
        )
        return {
            **report,
            "schema_version": "canonical-historical-learning-input.v1",
            "source_replay_schema_version": report.get("schema_version"),
            "source_runtime_version": report.get("runtime_version"),
            "decisions": cutoffs,
            "learning_observation_count": len(eligible),
            "calibration_eligible_observation_count": len(eligible),
            "governance_only_observation_count": int(
                report.get("governance_only_observation_count", 0) or 0
            ),
            "realized_outcome_count": horizon_count,
            "bounded_calibration_outcome_count": bounded_count,
            "outcome_alignment": "decision_horizon",
        }

    def run(
        self,
        *,
        start: date,
        end: date,
        cadence: str = "monthly",
        strict_only: bool = False,
        initial_portfolio_value: float = 250_000.0,
    ) -> dict[str, Any]:
        report = super().run(
            start=start,
            end=end,
            cadence=cadence,
            strict_only=strict_only,
            initial_portfolio_value=initial_portfolio_value,
        )
        observations = [
            observation
            for cutoff in report.get("decisions", [])
            if isinstance(cutoff, dict)
            for observation in cutoff.get("decisions", [])
            if isinstance(observation, dict)
        ]
        horizon_observations = [
            observation
            for observation in observations
            if isinstance(
                observation.get("realized_decision_value_at_horizon"),
                (int, float),
            )
            and not isinstance(
                observation.get("realized_decision_value_at_horizon"), bool
            )
        ]
        governance_only = sum(
            observation.get("calibration_eligible") is False
            for observation in observations
        )
        report.update(
            {
                "schema_version": "canonical-historical-replay.v4",
                "runtime_version": "single-pass-availability-cursor.v4",
                "learning_context_schema_version": "governed-historical-learning.v2",
                "calibration_eligible_observation_count": (
                    len(observations) - governance_only
                ),
                "governance_only_observation_count": governance_only,
                "realized_outcome_count": len(horizon_observations),
                "next_cutoff_outcome_count": sum(
                    isinstance(
                        observation.get(
                            "realized_decision_value_to_next_cutoff"
                        ),
                        (int, float),
                    )
                    and not isinstance(
                        observation.get(
                            "realized_decision_value_to_next_cutoff"
                        ),
                        bool,
                    )
                    for observation in observations
                ),
                "outcome_alignment": "decision_horizon",
                "avoided_loss_count": sum(
                    observation.get("realized_outcome") == "avoided_loss"
                    for observation in horizon_observations
                ),
                "missed_opportunity_count": sum(
                    observation.get("realized_outcome") == "missed_opportunity"
                    for observation in horizon_observations
                ),
            }
        )
        learning_report = self._learning_input_report(report)
        report["bounded_calibration_outcome_count"] = int(
            learning_report.get("bounded_calibration_outcome_count", 0) or 0
        )
        self.store.write_manifest("latest-canonical-replay", report)
        self.store.write_manifest(
            "latest-canonical-learning",
            learning_report,
        )
        return report


__all__ = ["HorizonAlignedCanonicalHistoricalReplayEngine"]
