"""Fail-closed production readiness across runtime and evidence boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from operations.heartbeat import WorkerHeartbeatStore


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class CompositeReadinessPolicy:
    component_maximum_age_seconds: Mapping[str, int]
    data_maximum_age_seconds: int
    backup_maximum_age_seconds: int
    require_exact_git_sha: bool = True


@dataclass(frozen=True, slots=True)
class CompositeReadinessReport:
    ready: bool
    evaluated_at: datetime
    deployed_git_sha: str
    components: Mapping[str, Mapping[str, Any]]
    schema_version: str = "capital-intelligence-composite-readiness.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "evaluated_at": self.evaluated_at.isoformat(),
            "deployed_git_sha": self.deployed_git_sha,
            "components": dict(self.components),
            "schema_version": self.schema_version,
            "paper_only": True,
            "real_money_authorized": False,
        }


def component_heartbeat_path(state_root: str | Path, component: str) -> Path:
    normalized = component.strip().lower()
    if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
        raise ValueError("component must use lowercase letters, numbers, and hyphens")
    return Path(state_root) / "component-heartbeats" / f"{normalized}.json"


def assess_composite_readiness(
    *,
    state_root: str | Path,
    deployed_git_sha: str,
    reconciliation_ready: bool,
    policy: CompositeReadinessPolicy,
    now: datetime | None = None,
) -> CompositeReadinessReport:
    evaluated_at = now or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    components: dict[str, dict[str, Any]] = {}
    heartbeats = {}
    for name, maximum_age in policy.component_maximum_age_seconds.items():
        healthy, detail, heartbeat = WorkerHeartbeatStore(
            component_heartbeat_path(state_root, name)
        ).health(maximum_age_seconds=maximum_age, now=evaluated_at)
        heartbeats[name] = heartbeat
        components[name] = {
            "required": True,
            "ready": healthy,
            "detail": detail,
            "observed_at": (
                None if heartbeat is None else heartbeat.observed_at.isoformat()
            ),
        }

    operator = heartbeats.get("cio-paper-operator")
    data_age = (
        None
        if operator is None
        else (evaluated_at - operator.observed_at).total_seconds()
    )
    data_ready = data_age is not None and 0 <= data_age <= policy.data_maximum_age_seconds
    components["data_freshness"] = {
        "required": True,
        "ready": data_ready,
        "detail": (
            "canonical operator evidence heartbeat is unavailable"
            if data_age is None
            else f"canonical operator evidence is {int(max(0, data_age))} seconds old"
        ),
        "observed_at": None if operator is None else operator.observed_at.isoformat(),
    }

    backup = heartbeats.get("encrypted-backup")
    backup_age = (
        None
        if backup is None
        else (evaluated_at - backup.observed_at).total_seconds()
    )
    backup_ready = (
        backup_age is not None
        and 0 <= backup_age <= policy.backup_maximum_age_seconds
        and backup.status == "healthy"
    )
    components["backup_age"] = {
        "required": True,
        "ready": backup_ready,
        "detail": (
            "successful encrypted-backup heartbeat is unavailable"
            if backup_age is None
            else f"latest successful encrypted backup is {int(max(0, backup_age))} seconds old"
        ),
        "observed_at": None if backup is None else backup.observed_at.isoformat(),
    }

    components["reconciliation"] = {
        "required": True,
        "ready": bool(reconciliation_ready),
        "detail": (
            "latest operational evidence has no reconciliation failures"
            if reconciliation_ready
            else "latest operational evidence is missing or has reconciliation failures"
        ),
        "observed_at": None,
    }

    exact_sha = deployed_git_sha.strip().lower()
    release_ready = bool(_GIT_SHA.fullmatch(exact_sha)) or not policy.require_exact_git_sha
    components["deployed_git_sha"] = {
        "required": policy.require_exact_git_sha,
        "ready": release_ready,
        "detail": (
            f"deployed release is exact Git SHA {exact_sha}"
            if release_ready and _GIT_SHA.fullmatch(exact_sha)
            else "deployed release is not an exact 40-character Git SHA"
        ),
        "observed_at": None,
    }

    return CompositeReadinessReport(
        ready=all(
            bool(component["ready"])
            for component in components.values()
            if bool(component["required"])
        ),
        evaluated_at=evaluated_at,
        deployed_git_sha=exact_sha,
        components=components,
    )


__all__ = [
    "CompositeReadinessPolicy",
    "CompositeReadinessReport",
    "assess_composite_readiness",
    "component_heartbeat_path",
]
