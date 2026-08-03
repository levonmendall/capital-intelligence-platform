"""Evidence-origin independence for committee confidence and sizing.

This module deliberately operates on the disclosed evidence graph rather than on
specialist headcount.  Several specialists that rely on the same originating fact
count as one partially independent confirmation, while their conclusions and
material dissent remain visible to the CIO.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cio.models import EvidenceDependency, SpecialistPosition, SpecialistRole


def _normalize(value: str) -> str:
    return str(value).strip().lower()


@dataclass(frozen=True, slots=True)
class EvidenceIndependenceAssessment:
    """Dependency-aware effective consensus for the four directional roles."""

    active_role_count: int
    effective_role_count: float
    independent_cluster_count: int
    unique_origin_count: int
    independence_ratio: float
    independent_support_ratio: float
    independent_opposition_ratio: float
    independent_confidence: float
    role_weights: tuple[tuple[SpecialistRole, float], ...]
    cluster_roles: tuple[tuple[SpecialistRole, ...], ...]

    def weight_for(self, role: SpecialistRole) -> float:
        return next((weight for item, weight in self.role_weights if item is role), 0.0)

    def independent_opposition_count(
        self,
        analyses: Iterable[object],
        *,
        minimum_confidence: float,
    ) -> int:
        by_role = {getattr(item, "role"): item for item in analyses}
        count = 0
        for cluster in self.cluster_roles:
            if any(
                getattr(by_role.get(role), "position", None)
                is SpecialistPosition.OPPOSED
                and float(getattr(by_role.get(role), "confidence", 0.0))
                >= minimum_confidence
                for role in cluster
            ):
                count += 1
        return count


def _dependency_map(analyses: tuple[object, ...]) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, tuple[str, ...]] = {}
    for analysis in analyses:
        for dependency in getattr(analysis, "evidence_dependencies", ()):
            if not isinstance(dependency, EvidenceDependency):
                continue
            identifier = _normalize(dependency.identifier)
            parents = tuple(_normalize(item) for item in dependency.parent_identifiers)
            mapping[identifier] = tuple(dict.fromkeys((*mapping.get(identifier, ()), *parents)))
    return mapping


def _closure(
    identifier: str,
    dependency_map: dict[str, tuple[str, ...]],
) -> frozenset[str]:
    pending = [_normalize(identifier)]
    seen: set[str] = set()
    while pending:
        item = pending.pop()
        if item in seen:
            continue
        seen.add(item)
        pending.extend(dependency_map.get(item, ()))
    return frozenset(seen)


def _origins(
    analysis: object,
    dependency_map: dict[str, tuple[str, ...]],
) -> frozenset[str]:
    declared = tuple(
        _normalize(item)
        for item in getattr(analysis, "evidence_origin_identifiers", ())
        if str(item).strip()
    )
    if not declared:
        role = getattr(analysis, "role")
        declared = (f"role:{role.value}:undeclared-origin",)
    return frozenset(
        ancestor
        for identifier in declared
        for ancestor in _closure(identifier, dependency_map)
    )


def _clusters(
    roles: tuple[SpecialistRole, ...],
    origin_sets: dict[SpecialistRole, frozenset[str]],
) -> tuple[tuple[SpecialistRole, ...], ...]:
    remaining = set(roles)
    values: list[tuple[SpecialistRole, ...]] = []
    while remaining:
        seed = min(remaining, key=lambda item: item.value)
        pending = [seed]
        connected: set[SpecialistRole] = set()
        while pending:
            role = pending.pop()
            if role in connected:
                continue
            connected.add(role)
            for other in tuple(remaining):
                if other in connected:
                    continue
                if origin_sets[role].intersection(origin_sets[other]):
                    pending.append(other)
        remaining.difference_update(connected)
        values.append(tuple(sorted(connected, key=lambda item: item.value)))
    return tuple(sorted(values, key=lambda cluster: cluster[0].value))


def assess_evidence_independence(
    analyses: Iterable[object],
) -> EvidenceIndependenceAssessment:
    """Return effective consensus after collapsing overlapping evidence clusters."""

    active = tuple(
        item
        for item in analyses
        if getattr(item, "position", None) is not SpecialistPosition.ABSTAIN
    )
    if not active:
        return EvidenceIndependenceAssessment(
            active_role_count=0,
            effective_role_count=0.0,
            independent_cluster_count=0,
            unique_origin_count=0,
            independence_ratio=0.0,
            independent_support_ratio=0.0,
            independent_opposition_ratio=0.0,
            independent_confidence=0.0,
            role_weights=(),
            cluster_roles=(),
        )
    dependency_map = _dependency_map(active)
    origin_sets = {
        getattr(item, "role"): _origins(item, dependency_map)
        for item in active
    }
    roles = tuple(getattr(item, "role") for item in active)
    clusters = _clusters(roles, origin_sets)
    weights: dict[SpecialistRole, float] = {}
    for cluster in clusters:
        cluster_weight = 1.0 / len(cluster)
        for role in cluster:
            weights[role] = cluster_weight
    effective = sum(weights.values())
    by_role = {getattr(item, "role"): item for item in active}
    supportive = sum(
        weights[role]
        for role in roles
        if getattr(by_role[role], "position") is SpecialistPosition.SUPPORTIVE
    )
    opposed = sum(
        weights[role]
        for role in roles
        if getattr(by_role[role], "position") is SpecialistPosition.OPPOSED
    )
    confidence = (
        0.0
        if effective <= 0.0
        else sum(
            float(getattr(by_role[role], "confidence")) * weights[role]
            for role in roles
        )
        / effective
    )
    origins = set().union(*(origin_sets[role] for role in roles))
    return EvidenceIndependenceAssessment(
        active_role_count=len(active),
        effective_role_count=round(effective, 8),
        independent_cluster_count=len(clusters),
        unique_origin_count=len(origins),
        independence_ratio=round(effective / len(active), 8),
        independent_support_ratio=round(supportive / effective, 8),
        independent_opposition_ratio=round(opposed / effective, 8),
        independent_confidence=round(confidence, 8),
        role_weights=tuple(sorted(weights.items(), key=lambda item: item[0].value)),
        cluster_roles=clusters,
    )


__all__ = [
    "EvidenceIndependenceAssessment",
    "assess_evidence_independence",
]
