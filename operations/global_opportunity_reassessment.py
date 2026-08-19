"""Cross-market leadership trigger for the canonical CIO reassessment loop.

The existing reassessment stack already owns market snapshots, schedule guards,
content materiality, reactive thesis dependencies, deduplication, and cooldown.  This
layer adds one missing question: has relative leadership moved far enough across the
active global opportunity set that the CIO should reconsider where marginal capital
belongs?

It can request reassessment only.  It cannot create a candidate, choose an action,
size capital, construct a portfolio, execute a fill, or authorize real money.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from operations.cio_material_reassessment import (
    ReassessmentResult,
    aware_utc,
    load_json,
    parse_datetime,
    save_json,
)
from operations.reactive_investor_material_reassessment import (
    ReactiveInvestorMaterialCIOReassessmentEngine,
)


_DOMAIN_BY_EXPOSURE = {
    "us_equity": "equity",
    "international_equity": "equity",
    "government_bonds": "fixed_income",
    "investment_grade_credit": "credit",
    "high_yield_credit": "credit",
    "cash_treasury": "fixed_income",
    "broad_commodities": "commodity",
    "gold": "commodity",
    "foreign_exchange": "currency",
    "crypto": "crypto",
    "real_estate": "real_estate",
    "managed_futures": "alternative",
    "option_strategies": "volatility",
    "volatility": "volatility",
    "market_neutral_alternatives": "alternative",
}
_DOMAIN_BY_ASSET_CLASS = {
    "us_equity": "equity",
    "us_etf": "equity",
    "international_equity": "equity",
    "fixed_income": "fixed_income",
    "cash_equivalent": "fixed_income",
    "commodity": "commodity",
    "future": "alternative",
    "fx": "currency",
    "crypto": "crypto",
    "real_estate": "real_estate",
    "option": "volatility",
    "volatility": "volatility",
    "alternative": "alternative",
}


class GlobalOpportunityMaterialCIOReassessmentEngine(
    ReactiveInvestorMaterialCIOReassessmentEngine
):
    """Request review when cross-domain leadership changes materially."""

    def __init__(
        self,
        *,
        leadership_spread_threshold: float = 0.02,
        leadership_change_threshold: float = 0.0125,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not 0.0 < float(leadership_spread_threshold) <= 1.0:
            raise ValueError("leadership_spread_threshold must be in (0, 1]")
        if not 0.0 < float(leadership_change_threshold) <= 1.0:
            raise ValueError("leadership_change_threshold must be in (0, 1]")
        self.leadership_spread_threshold = float(leadership_spread_threshold)
        self.leadership_change_threshold = float(leadership_change_threshold)

    def _symbol_domains(self) -> Mapping[str, str]:
        payload = load_json(self.active_universe_path)
        universe = payload.get("universe")
        instruments = universe.get("instruments") if isinstance(universe, Mapping) else None
        if not isinstance(instruments, list):
            return {}
        domains: dict[str, str] = {}
        for item in instruments:
            if not isinstance(item, Mapping):
                continue
            symbol = str(item.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            exposure = str(item.get("economic_exposure", "")).strip().lower()
            asset_class = str(item.get("execution_asset_class", "")).strip().lower()
            domains[symbol] = _DOMAIN_BY_EXPOSURE.get(
                exposure,
                _DOMAIN_BY_ASSET_CLASS.get(asset_class, "other"),
            )
        return domains

    def _leadership_change(
        self,
        *,
        state: Mapping[str, Any],
    ) -> tuple[str | None, tuple[str, ...], Mapping[str, float]]:
        current = state.get("last_prices")
        baseline = state.get("assessment_prices")
        if not isinstance(current, Mapping) or not isinstance(baseline, Mapping):
            return None, (), {}
        domains = self._symbol_domains()
        moves: dict[str, list[float]] = {}
        for symbol, raw_current in current.items():
            if symbol not in domains:
                continue
            raw_baseline = baseline.get(symbol)
            if (
                isinstance(raw_current, bool)
                or not isinstance(raw_current, (int, float))
                or isinstance(raw_baseline, bool)
                or not isinstance(raw_baseline, (int, float))
                or float(raw_current) <= 0.0
                or float(raw_baseline) <= 0.0
            ):
                continue
            move = float(raw_current) / float(raw_baseline) - 1.0
            moves.setdefault(domains[symbol], []).append(move)
        if len(moves) < 2:
            return None, (), {}
        domain_scores = {
            domain: sum(values) / len(values) for domain, values in moves.items() if values
        }
        if len(domain_scores) < 2:
            return None, (), {}
        ordered = sorted(domain_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        leader, leader_score = ordered[0]
        runner_up_score = ordered[1][1]
        spread = leader_score - runner_up_score
        prior_leader = str(state.get("global_opportunity_leader_domain", "")).strip()
        prior_score = state.get("global_opportunity_leader_score")
        prior_score_value = (
            float(prior_score)
            if isinstance(prior_score, (int, float)) and not isinstance(prior_score, bool)
            else None
        )
        reasons: list[str] = []
        if spread >= self.leadership_spread_threshold and leader_score > 0.0:
            reasons.append(
                f"global opportunity leadership spread favors {leader}: "
                f"{leader_score:+.2%} versus {runner_up_score:+.2%} for the runner-up domain"
            )
        if (
            prior_leader
            and prior_leader != leader
            and leader_score >= self.leadership_change_threshold
        ):
            reasons.append(
                f"global opportunity leadership rotated from {prior_leader} to {leader}"
            )
        if (
            prior_leader == leader
            and prior_score_value is not None
            and leader_score - prior_score_value >= self.leadership_change_threshold
        ):
            reasons.append(
                f"{leader} leadership strengthened by {leader_score - prior_score_value:+.2%} since the last acknowledged CIO assessment"
            )
        return leader, tuple(dict.fromkeys(reasons)), domain_scores

    def scan_if_due(
        self,
        *,
        now: datetime,
        public_collection: object | None = None,
    ) -> ReassessmentResult:
        timestamp = aware_utc(now, "now")
        base = super().scan_if_due(now=timestamp, public_collection=public_collection)
        if base.triggered or base.state in {
            "not_due",
            "scheduled_guard",
            "failed",
            "market_closed",
            "cooldown",
        }:
            return base
        state = load_json(self.state_path)
        leader, reasons, domain_scores = self._leadership_change(state=state)
        if leader is None:
            return base
        state["latest_global_opportunity_leader_domain"] = leader
        state["latest_global_opportunity_domain_scores"] = {
            key: round(value, 8) for key, value in sorted(domain_scores.items())
        }
        if not reasons:
            save_json(self.state_path, state)
            return base

        combined = tuple(dict.fromkeys((*base.reasons, *reasons)))
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "revision": int(state.get("baseline_revision", 0) or 0),
                    "leader": leader,
                    "domain_scores": state["latest_global_opportunity_domain_scores"],
                    "reasons": combined,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if state.get("last_trigger_fingerprint") == fingerprint:
            save_json(self.state_path, state)
            return ReassessmentResult(
                state="deduplicated",
                evaluated_at=timestamp,
                reasons=combined,
                symbol_count=base.symbol_count,
                detail="The same cross-market leadership condition already requested CIO reassessment.",
            )
        last_triggered = parse_datetime(state.get("last_triggered_at"))
        if last_triggered is not None and timestamp - last_triggered < self.event_cooldown:
            save_json(self.state_path, state)
            return ReassessmentResult(
                state="cooldown",
                evaluated_at=timestamp,
                reasons=combined,
                symbol_count=base.symbol_count,
                detail="Global leadership changed inside the current CIO event cooldown.",
            )
        local = timestamp.astimezone(self.timezone)
        trigger_key = (
            f"global-opportunity-{local.strftime('%Y%m%d-%H%M')}-{fingerprint[:12]}"
        )
        state.update(
            {
                "last_triggered_at": timestamp.isoformat(),
                "last_trigger_fingerprint": fingerprint,
                "last_trigger_key": trigger_key,
            }
        )
        save_json(self.state_path, state)
        return ReassessmentResult(
            state="triggered",
            evaluated_at=timestamp,
            triggered=True,
            trigger_key=trigger_key,
            reasons=combined,
            symbol_count=base.symbol_count,
            detail=(
                "Cross-market relative leadership changed enough to request a full canonical CIO reassessment. "
                "The trigger itself has no investment or execution authority."
            ),
        )

    def acknowledge_assessment(self, *, now: datetime) -> None:
        super().acknowledge_assessment(now=now)
        state = load_json(self.state_path)
        leader = str(state.get("latest_global_opportunity_leader_domain", "")).strip()
        scores = state.get("latest_global_opportunity_domain_scores")
        if leader and isinstance(scores, Mapping):
            state["global_opportunity_leader_domain"] = leader
            score = scores.get(leader)
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                state["global_opportunity_leader_score"] = float(score)
        save_json(self.state_path, state)


__all__ = ["GlobalOpportunityMaterialCIOReassessmentEngine"]
