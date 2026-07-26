"""Production data-source enablement for market engines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

REQUIRED_PRODUCTION_ENGINES = (
    "market_breadth",
    "valuation",
    "technical_momentum",
    "risk",
)


class DataEnablementStatus(str, Enum):
    AUTHORITATIVE = "authoritative"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    engine: str
    provider: str
    licensed: bool
    point_in_time: bool
    historical_universe: bool
    corporate_actions: bool
    adjustment_policy_version: str | None
    provenance_complete: bool
    service_level_defined: bool

    def deficiencies(self) -> tuple[str, ...]:
        checks = {
            "licensed source": self.licensed,
            "point-in-time availability": self.point_in_time,
            "historical universe": self.historical_universe,
            "corporate actions": self.corporate_actions,
            "versioned adjustment policy": bool(self.adjustment_policy_version),
            "complete provenance": self.provenance_complete,
            "service-level policy": self.service_level_defined,
        }
        return tuple(name for name, passed in checks.items() if not passed)

    @property
    def ready(self) -> bool:
        return not self.deficiencies()


@dataclass(frozen=True, slots=True)
class DataEnablementReport:
    status: DataEnablementStatus
    capabilities: tuple[ProviderCapability, ...]
    missing_engines: tuple[str, ...]
    deficient_engines: tuple[str, ...]
    authoritative_decisions_allowed: bool
    synthetic_fallback_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "production-data-enablement.v1",
            "status": self.status.value,
            "required_engines": list(REQUIRED_PRODUCTION_ENGINES),
            "missing_engines": list(self.missing_engines),
            "deficient_engines": list(self.deficient_engines),
            "authoritative_decisions_allowed": self.authoritative_decisions_allowed,
            "synthetic_fallback_allowed": self.synthetic_fallback_allowed,
            "capabilities": [
                {
                    "engine": item.engine,
                    "provider": item.provider,
                    "ready": item.ready,
                    "deficiencies": list(item.deficiencies()),
                    "licensed": item.licensed,
                    "point_in_time": item.point_in_time,
                    "historical_universe": item.historical_universe,
                    "corporate_actions": item.corporate_actions,
                    "adjustment_policy_version": item.adjustment_policy_version,
                    "provenance_complete": item.provenance_complete,
                    "service_level_defined": item.service_level_defined,
                }
                for item in self.capabilities
            ],
        }


def evaluate_production_data(
    capabilities: Iterable[ProviderCapability],
) -> DataEnablementReport:
    values = tuple(capabilities)
    by_engine: dict[str, ProviderCapability] = {}
    for item in values:
        if item.engine not in REQUIRED_PRODUCTION_ENGINES:
            raise ValueError(f"unknown production engine: {item.engine}")
        if item.engine in by_engine:
            raise ValueError(f"duplicate provider capability: {item.engine}")
        if not item.provider.strip():
            raise ValueError("provider is required")
        by_engine[item.engine] = item

    missing = tuple(engine for engine in REQUIRED_PRODUCTION_ENGINES if engine not in by_engine)
    ordered = tuple(by_engine[engine] for engine in REQUIRED_PRODUCTION_ENGINES if engine in by_engine)
    deficient = tuple(item.engine for item in ordered if not item.ready)
    if not ordered:
        status = DataEnablementStatus.UNAVAILABLE
    elif missing or deficient:
        status = DataEnablementStatus.PARTIAL
    else:
        status = DataEnablementStatus.AUTHORITATIVE
    return DataEnablementReport(
        status=status,
        capabilities=ordered,
        missing_engines=missing,
        deficient_engines=deficient,
        authoritative_decisions_allowed=status is DataEnablementStatus.AUTHORITATIVE,
    )
