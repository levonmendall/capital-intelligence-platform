from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

@dataclass(frozen=True)
class MarketSnapshot:
    as_of: str
    source: str
    signals: dict[str, float]
    opportunity_features: dict[str, dict[str, float]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.as_of:
            raise ValueError("as_of is required")
        for name, value in self.signals.items():
            if not 0 <= float(value) <= 100:
                raise ValueError(f"Signal {name} must be normalized to 0..100")

    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True)
class Evidence:
    signal: str
    value: float
    interpretation: str
    contribution: float

@dataclass(frozen=True)
class CouncilOpinion:
    specialist_id: str
    specialist_name: str
    score: float
    confidence: float
    recommendation: str
    evidence: tuple[Evidence, ...]
    risk_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True)
class RegimeResult:
    primary_regime: str
    probabilities: dict[str, float]
    confidence: float
    raw_scores: dict[str, float]
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True)
class OpportunityScore:
    category: str
    opportunity_id: str
    label: str
    symbol: str
    score: float
    confidence: float
    components: dict[str, float]
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True)
class CIOIntelligenceDecision:
    created_at: str
    snapshot_as_of: str
    model_version: str
    regime: RegimeResult
    council: tuple[CouncilOpinion, ...]
    opportunity_rankings: dict[str, tuple[OpportunityScore, ...]]
    composite_risk_score: float
    confidence: float
    summary: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]: return asdict(self)
