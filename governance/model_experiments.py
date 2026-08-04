"""Governed shadow experiments for investment models.

Experiments compare a production champion with one or more challengers using the same
point-in-time evidence. A challenger is never allowed to alter production capital,
policy, specialist votes, CIO decisions, construction, or execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ExperimentStatus(str, Enum):
    REGISTERED = "registered"
    SHADOW_RUNNING = "shadow_running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    PROMOTED = "promoted"


@dataclass(frozen=True, slots=True)
class ModelExperiment:
    identifier: str
    champion_model_version: str
    challenger_model_version: str
    registered_at: datetime
    evidence_contract_version: str
    hypothesis: str
    minimum_sample_size: int
    out_of_sample_required: bool = True
    survivorship_safe_required: bool = True
    paper_shadow_required: bool = True
    status: ExperimentStatus = ExperimentStatus.REGISTERED
    schema_version: str = "model-experiment.v1"

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "champion_model_version",
            "challenger_model_version",
            "evidence_contract_version",
            "hypothesis",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.champion_model_version == self.challenger_model_version:
            raise ValueError("champion and challenger versions must differ")
        if self.registered_at.tzinfo is None or self.registered_at.utcoffset() is None:
            raise ValueError("registered_at must be timezone-aware")
        if isinstance(self.minimum_sample_size, bool) or self.minimum_sample_size < 1:
            raise ValueError("minimum_sample_size must be positive")
        if not isinstance(self.status, ExperimentStatus):
            raise TypeError("status must be ExperimentStatus")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "champion_model_version": self.champion_model_version,
            "challenger_model_version": self.challenger_model_version,
            "registered_at": self.registered_at.isoformat(),
            "evidence_contract_version": self.evidence_contract_version,
            "hypothesis": self.hypothesis,
            "minimum_sample_size": self.minimum_sample_size,
            "out_of_sample_required": self.out_of_sample_required,
            "survivorship_safe_required": self.survivorship_safe_required,
            "paper_shadow_required": self.paper_shadow_required,
            "status": self.status.value,
            "production_capital_authorized": False,
        }


@dataclass(frozen=True, slots=True)
class ShadowModelObservation:
    identifier: str
    experiment_identifier: str
    as_of: datetime
    evidence_package_identifier: str
    evidence_cutoff: datetime
    champion_forecast: float
    challenger_forecast: float
    champion_rank: int | None
    challenger_rank: int | None
    champion_action: str
    challenger_action: str
    champion_size: float
    challenger_size: float
    expected_benefit: float
    realized_outcome: float | None
    champion_calibration_loss: float | None
    challenger_calibration_loss: float | None
    champion_turnover: float
    challenger_turnover: float
    champion_drawdown: float | None
    challenger_drawdown: float | None
    out_of_sample: bool
    survivorship_safe: bool

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.experiment_identifier.strip():
            raise ValueError("observation identifiers are required")
        for name in ("as_of", "evidence_cutoff"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.evidence_cutoff > self.as_of:
            raise ValueError("evidence cutoff cannot follow observation time")
        for name in (
            "champion_size",
            "challenger_size",
            "champion_turnover",
            "challenger_turnover",
        ):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} cannot be negative")


__all__ = [
    "ExperimentStatus",
    "ModelExperiment",
    "ShadowModelObservation",
]
