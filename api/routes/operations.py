"""Operational liveness, worker health, and metrics endpoints."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request, Response, status

from operations import WorkerHeartbeatStore

router = APIRouter(tags=["operations"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/worker/health")
def worker_health(request: Request, response: Response) -> dict[str, object]:
    settings = request.app.state.operational_settings
    store = WorkerHeartbeatStore(settings.worker_heartbeat_path)
    healthy, detail, heartbeat = store.health(
        maximum_age_seconds=settings.worker_max_age_seconds
    )
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "healthy": healthy,
        "detail": detail,
        "heartbeat": None if heartbeat is None else heartbeat.to_dict(),
    }


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    settings = request.app.state.operational_settings
    expected = settings.metrics_token
    if expected:
        supplied = request.headers.get("authorization", "")
        prefix = "Bearer "
        token = supplied[len(prefix) :] if supplied.startswith(prefix) else ""
        if not hmac.compare_digest(token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="metrics authentication is required",
                headers={"WWW-Authenticate": "Bearer"},
            )
    content = request.app.state.metrics.render()
    return Response(content=content, media_type="text/plain; version=0.0.4")


__all__ = ["router"]
