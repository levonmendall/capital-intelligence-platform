"""Certified decision-time Environment and post-decision developments."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.canonical_environment import CanonicalEnvironmentRepository
from api.config import ApiSettings
from api.dependencies import get_resources, get_settings
from api.repositories import ApiResources

router = APIRouter(prefix="/v1/environment", tags=["environment"])


@router.get("/latest")
def latest_environment(
    resources: ApiResources = Depends(get_resources),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    canonical = CanonicalEnvironmentRepository(
        settings.environment_database,
        required=settings.require_canonical_environment,
    )
    view = canonical.latest_view()
    if view is not None:
        return {
            **view,
            "sources": dict(view["source_versions"]),
            "subsequent_developments_are_decision_evidence": False,
        }
    if settings.require_canonical_environment:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "certified decision Environment snapshot is required but unavailable"
            ),
        )

    # Explicit compatibility boundary for development fixtures created before the
    # canonical Environment authority. Production never reaches this branch.
    payload = resources.snapshots.latest_payload()
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no canonical environment snapshot is available",
        )
    environment = payload.get("environment")
    sources = payload.get("sources")
    if not isinstance(environment, dict) or not isinstance(sources, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="latest snapshot does not contain the legacy Environment contract",
        )
    return {
        "snapshot_identifier": str(payload["identifier"]),
        "as_of": str(payload["as_of"]),
        "environment": environment,
        "sources": {str(key): str(value) for key, value in sources.items()},
        "decision_time_certified": False,
        "subsequent_observations": [],
        "subsequent_observation_count": 0,
        "subsequent_developments_are_decision_evidence": False,
        "schema_version": "legacy-environment-compatibility.v1",
    }


__all__ = ["router"]
