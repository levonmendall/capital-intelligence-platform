"""Operational liveness, worker health, and metrics endpoints."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request, Response, status

from operations import WorkerHeartbeatStore

router = APIRouter(tags=["operations"])


def _require_metrics_auth(request: Request) -> None:
    settings = request.app.state.operational_settings
    expected = settings.metrics_token
    if expected:
        supplied = request.headers.get("authorization", "")
        prefix = "Bearer "
        token = supplied[len(prefix) :] if supplied.startswith(prefix) else ""
        if not hmac.compare_digest(token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="operational authentication is required",
                headers={"WWW-Authenticate": "Bearer"},
            )


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




@router.get("/operations/slo")
def operational_slo(request: Request, response: Response) -> dict[str, object]:
    _require_metrics_auth(request)
    snapshot = request.app.state.operational_slo_service.assess()
    snapshot.publish_metrics(request.app.state.metrics)
    if (
        request.app.state.operational_settings.require_operational_slos
        and not snapshot.ready
    ):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot.to_dict()


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    _require_metrics_auth(request)
    snapshot = request.app.state.operational_slo_service.assess()
    snapshot.publish_metrics(request.app.state.metrics)
    content = request.app.state.metrics.render()
    return Response(content=content, media_type="text/plain; version=0.0.4")


__all__ = ["router"]
