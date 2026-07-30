"""Calibration-safe live resolver for governed historical learning.

The replay manifest shown in History contains every governed observation, including
capability-policy-only abstentions. Live forecast, confidence, and sizing calibration
consume a separate manifest that excludes those policy-only observations, maps
realized results to the original decision horizon, and certifies complete point-in-time
macro coverage.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from cio.historical_learning import (
    HistoricalLearningContext,
    HistoricalLearningResolver as _BaseHistoricalLearningResolver,
)
from cio.models import CandidateDecisionRecord


class HistoricalLearningResolver(_BaseHistoricalLearningResolver):
    """Resolve only macro-complete, horizon-aligned calibration evidence."""

    @classmethod
    def from_environment(cls) -> "HistoricalLearningResolver":
        root = Path(
            os.getenv(
                "CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR",
                "database/historical_replay",
            )
        )
        minimum = int(
            os.getenv(
                "CAPITAL_INTELLIGENCE_HISTORICAL_LEARNING_MINIMUM_SAMPLE",
                "6",
            )
        )
        return cls(
            root / "manifests" / "latest-canonical-learning.json",
            minimum_sample_size=minimum,
        )

    def resolve(
        self,
        candidate: CandidateDecisionRecord,
        *,
        as_of: datetime,
        macro_regime: str,
        market_regime: str,
    ) -> HistoricalLearningContext:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason=(
                    "Calibration-safe historical learning is unavailable because the "
                    "horizon-aligned learning manifest has not completed."
                ),
            )
        if payload.get("schema_version") != "canonical-historical-learning-input.v1":
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason="Historical learning was excluded because its calibration schema is unsupported.",
            )
        if payload.get("outcome_alignment") != "decision_horizon":
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason=(
                    "Historical learning was excluded because realized outcomes were "
                    "not aligned to the original decision horizon."
                ),
            )
        if payload.get("macro_coverage_satisfied") is not True:
            missing = payload.get("required_macro_datasets")
            detail = (
                ", ".join(str(item) for item in missing)
                if isinstance(missing, list) and missing
                else "required policy-rate, yield-curve, and volatility series"
            )
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason=(
                    "Historical learning was excluded because complete point-in-time "
                    f"macro coverage was not certified for {detail}."
                ),
            )
        if payload.get("certification_ready") is not True:
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason=(
                    "Historical learning was excluded because its canonical replay "
                    "certification is not complete."
                ),
            )

        context = super().resolve(
            candidate,
            as_of=as_of,
            macro_regime=macro_regime,
            market_regime=market_regime,
        )
        excluded = int(payload.get("governance_only_observation_count", 0) or 0)
        bounded = int(payload.get("bounded_calibration_outcome_count", 0) or 0)
        macro_excluded = int(payload.get("macro_excluded_observation_count", 0) or 0)
        limitations: list[str] = []
        identifiers: list[str] = []
        if excluded > 0:
            limitations.append(
                f"{excluded} capability-policy-only historical observations were retained "
                "for governance review but excluded from forecast, confidence, and position-size calibration."
            )
            identifiers.append(
                f"historical-learning:governance-only-excluded:{excluded}"
            )
        if macro_excluded > 0:
            limitations.append(
                f"{macro_excluded} historical observations from macro-incomplete cutoffs "
                "were retained for audit but excluded from live calibration."
            )
            identifiers.append(
                f"historical-learning:macro-incomplete-excluded:{macro_excluded}"
            )
        if bounded > 0:
            limitations.append(
                f"{bounded} extreme decision-relative regret observations were preserved "
                "at full value in the research archive but bounded at -100% in the live calibration input."
            )
            identifiers.append(
                f"historical-learning:bounded-calibration-outcomes:{bounded}"
            )
        if not limitations:
            return context
        note = " ".join(limitations)
        return replace(
            context,
            summary=f"{context.summary} {note}",
            limitations=tuple(
                dict.fromkeys(context.limitations + tuple(limitations))
            ),
            evidence_identifiers=tuple(
                dict.fromkeys(
                    context.evidence_identifiers + tuple(identifiers)
                )
            ),
        )


__all__ = ["HistoricalLearningResolver"]
