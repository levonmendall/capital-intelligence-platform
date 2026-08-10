"""Canonical information-capability and gap registry.

This registry separates code presence, operating readiness, point-in-time suitability,
historical depth, decision certification, and allocation capability.  It is an
observability/governance contract only and has no investment authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class CoverageScope(str, Enum):
    MONITORED = "monitored"
    DECISION_CERTIFIED = "decision_certified"
    ALLOCATABLE = "allocatable"


@dataclass(frozen=True, slots=True)
class InformationCapabilityRecord:
    identifier: str
    domains: tuple[str, ...]
    markets: tuple[str, ...] = ()
    asset_classes: tuple[str, ...] = ()
    implemented: bool = False
    configured: bool = False
    credentialed: bool = False
    reachable: bool = False
    collecting: bool = False
    point_in_time_capable: bool = False
    historical_capable: bool = False
    decision_certified: bool = False
    allocatable: bool = False
    healthy: bool = False
    source_independence_group: str = "unknown"
    limitations: tuple[str, ...] = ()
    schema_version: str = "information-capability.v1"

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("identifier cannot be empty")
        if not self.domains or any(not item.strip() for item in self.domains):
            raise ValueError("domains must contain non-empty values")
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("domains cannot contain duplicates")
        if self.decision_certified and not all(
            (
                self.implemented,
                self.configured,
                self.reachable,
                self.point_in_time_capable,
            )
        ):
            raise ValueError(
                "decision-certified capability requires implemented, configured, "
                "reachable, point-in-time-capable evidence"
            )
        if self.allocatable and not self.decision_certified:
            raise ValueError("allocatable capability must be decision certified")
        if self.healthy and not self.reachable:
            raise ValueError("healthy capability must be reachable")

    @property
    def scope(self) -> CoverageScope:
        if self.allocatable:
            return CoverageScope.ALLOCATABLE
        if self.decision_certified:
            return CoverageScope.DECISION_CERTIFIED
        return CoverageScope.MONITORED

    @property
    def readiness_fraction(self) -> float:
        flags = (
            self.implemented,
            self.configured,
            self.credentialed,
            self.reachable,
            self.collecting,
            self.point_in_time_capable,
            self.historical_capable,
            self.decision_certified,
            self.healthy,
        )
        return round(sum(bool(item) for item in flags) / len(flags), 8)


@dataclass(frozen=True, slots=True)
class InformationGap:
    domain: str
    required_scope: CoverageScope
    reason: str
    candidate_capabilities: tuple[str, ...]
    remediation: tuple[str, ...]


class InformationCapabilityRegistry:
    """Single query surface for source readiness and information gaps."""

    def __init__(self, records: Iterable[InformationCapabilityRecord]) -> None:
        values = tuple(records)
        identifiers = tuple(item.identifier for item in values)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("capability identifiers must be unique")
        self.records = values

    def for_domain(self, domain: str) -> tuple[InformationCapabilityRecord, ...]:
        normalized = domain.strip().casefold()
        return tuple(
            item
            for item in self.records
            if normalized in {value.casefold() for value in item.domains}
        )

    def coverage(
        self,
        domain: str,
        *,
        required_scope: CoverageScope = CoverageScope.DECISION_CERTIFIED,
    ) -> bool:
        values = self.for_domain(domain)
        if required_scope is CoverageScope.MONITORED:
            return any(item.implemented for item in values)
        if required_scope is CoverageScope.DECISION_CERTIFIED:
            return any(item.decision_certified and item.healthy for item in values)
        return any(item.allocatable and item.healthy for item in values)

    def gaps(
        self,
        required_domains: Iterable[str],
        *,
        required_scope: CoverageScope = CoverageScope.DECISION_CERTIFIED,
    ) -> tuple[InformationGap, ...]:
        output: list[InformationGap] = []
        for domain in tuple(dict.fromkeys(item.strip() for item in required_domains if item.strip())):
            if self.coverage(domain, required_scope=required_scope):
                continue
            candidates = self.for_domain(domain)
            remediation: list[str] = []
            if not candidates:
                remediation.append("implement at least one governed source")
            else:
                if not any(item.reachable for item in candidates):
                    remediation.append("restore provider reachability")
                if not any(item.point_in_time_capable for item in candidates):
                    remediation.append("add point-in-time availability and revision lineage")
                if required_scope is not CoverageScope.MONITORED and not any(
                    item.decision_certified for item in candidates
                ):
                    remediation.append("complete decision-evidence certification")
                if required_scope is CoverageScope.ALLOCATABLE and not any(
                    item.allocatable for item in candidates
                ):
                    remediation.append("complete execution/custody/settlement capability")
                if not any(item.historical_capable for item in candidates):
                    remediation.append("backfill certified historical coverage")
            output.append(
                InformationGap(
                    domain=domain,
                    required_scope=required_scope,
                    reason=(
                        f"No healthy {required_scope.value} capability currently "
                        f"satisfies {domain}."
                    ),
                    candidate_capabilities=tuple(item.identifier for item in candidates),
                    remediation=tuple(dict.fromkeys(remediation)),
                )
            )
        return tuple(output)

    def summary(self) -> dict[str, object]:
        domains = tuple(sorted({domain for item in self.records for domain in item.domains}))
        return {
            "schema_version": "information-capability-registry.v1",
            "capability_count": len(self.records),
            "domain_count": len(domains),
            "monitored_domains": [
                domain for domain in domains if self.coverage(domain, required_scope=CoverageScope.MONITORED)
            ],
            "decision_certified_domains": [
                domain for domain in domains if self.coverage(domain)
            ],
            "allocatable_domains": [
                domain for domain in domains if self.coverage(domain, required_scope=CoverageScope.ALLOCATABLE)
            ],
            "investment_authority": False,
            "real_money_authorized": False,
        }


__all__ = [
    "CoverageScope",
    "InformationCapabilityRecord",
    "InformationCapabilityRegistry",
    "InformationGap",
]
