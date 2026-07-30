"""Macro-complete governed historical replay certification.

The v4 runtime separates audit evidence from calibration-safe evidence and aligns
outcomes to each decision horizon. This layer adds the final macro-integrity gate:
completed historical cutoffs must have point-in-time policy-rate, yield-curve, and
volatility evidence. Price-only cutoffs remain visible for audit but are excluded from
the live learning sidecar, and the command cannot certify until required coverage is
complete.
"""

from __future__ import annotations

import gzip
import json
from bisect import bisect_right
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .canonical_runtime_v4 import HorizonAlignedCanonicalHistoricalReplayEngine
from .models import HistoricalRecord

UTC = timezone.utc
REQUIRED_MACRO_DATASETS = (
    "series.fedfunds",
    "series.t10y2y",
    "series.vixcls",
)


def _cutoff_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


class MacroCompleteCanonicalHistoricalReplayEngine(
    HorizonAlignedCanonicalHistoricalReplayEngine
):
    """Certify only cutoffs with complete point-in-time macro evidence."""

    def _macro_availability(self) -> dict[str, tuple[datetime, ...]]:
        coverage: dict[str, tuple[datetime, ...]] = {}
        for dataset in REQUIRED_MACRO_DATASETS:
            dataset_root = self.store.records_root / "fred" / dataset
            available: list[datetime] = []
            for path in sorted(dataset_root.glob("year=*/records.jsonl.gz")):
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    for line in stream:
                        if not line.strip():
                            continue
                        payload = json.loads(line)
                        record = HistoricalRecord(**payload)
                        if not record.strict_replay_eligible:
                            continue
                        available.append(record.available_datetime)
            coverage[dataset] = tuple(sorted(set(available)))
        return coverage

    @staticmethod
    def _missing_at_cutoff(
        coverage: dict[str, tuple[datetime, ...]],
        cutoff: datetime,
    ) -> tuple[str, ...]:
        return tuple(
            dataset
            for dataset in REQUIRED_MACRO_DATASETS
            if not coverage.get(dataset)
            or bisect_right(coverage[dataset], cutoff) == 0
        )

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
        coverage = self._macro_availability()
        present = tuple(
            dataset for dataset in REQUIRED_MACRO_DATASETS if coverage.get(dataset)
        )
        missing_datasets = tuple(
            dataset for dataset in REQUIRED_MACRO_DATASETS if not coverage.get(dataset)
        )

        safe_report = deepcopy(report)
        safe_cutoffs: list[dict[str, Any]] = []
        macro_incomplete_cutoffs = 0
        macro_excluded_observations = 0
        for cutoff in report.get("decisions", []):
            if not isinstance(cutoff, dict):
                continue
            cutoff_at = _cutoff_datetime(cutoff.get("cutoff"))
            missing = (
                self._missing_at_cutoff(coverage, cutoff_at)
                if cutoff_at is not None
                else REQUIRED_MACRO_DATASETS
            )
            complete = not missing
            cutoff["macro_coverage_complete"] = complete
            cutoff["missing_macro_datasets"] = list(missing)
            if cutoff.get("state") == "completed" and not complete:
                macro_incomplete_cutoffs += 1
                observations = cutoff.get("decisions")
                if isinstance(observations, list):
                    macro_excluded_observations += sum(
                        isinstance(item, dict) for item in observations
                    )
            if cutoff.get("state") != "completed" or complete:
                safe_cutoffs.append(deepcopy(cutoff))

        safe_report["decisions"] = safe_cutoffs
        learning_report = self._learning_input_report(safe_report)
        certification_ready = (
            int(report.get("canonical_cio_invoked_count", 0) or 0) > 0
            and not missing_datasets
            and macro_incomplete_cutoffs == 0
        )
        report.update(
            {
                "schema_version": "canonical-historical-replay.v5",
                "runtime_version": "single-pass-availability-cursor.v5",
                "learning_context_schema_version": "governed-historical-learning.v3",
                "required_macro_datasets": list(REQUIRED_MACRO_DATASETS),
                "present_macro_datasets": list(present),
                "missing_macro_datasets": list(missing_datasets),
                "required_macro_dataset_count": len(REQUIRED_MACRO_DATASETS),
                "present_macro_dataset_count": len(present),
                "macro_coverage_satisfied": not missing_datasets
                and macro_incomplete_cutoffs == 0,
                "macro_incomplete_cutoff_count": macro_incomplete_cutoffs,
                "macro_excluded_observation_count": macro_excluded_observations,
                "calibration_eligible_observation_count": int(
                    learning_report.get(
                        "calibration_eligible_observation_count",
                        0,
                    )
                    or 0
                ),
                "certification_ready": certification_ready,
            }
        )
        learning_report.update(
            {
                "source_replay_schema_version": report["schema_version"],
                "source_runtime_version": report["runtime_version"],
                "macro_coverage_satisfied": report["macro_coverage_satisfied"],
                "required_macro_datasets": list(REQUIRED_MACRO_DATASETS),
                "macro_excluded_observation_count": macro_excluded_observations,
                "certification_ready": certification_ready,
            }
        )
        self.store.write_manifest("latest-canonical-replay", report)
        self.store.write_manifest("latest-canonical-learning", learning_report)
        return report


__all__ = [
    "MacroCompleteCanonicalHistoricalReplayEngine",
    "REQUIRED_MACRO_DATASETS",
]
