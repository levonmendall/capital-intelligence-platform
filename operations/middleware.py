"""Request correlation, rate limiting, size limits, metrics, and hardening."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from operations.logging import set_request_id
from operations.metrics import MetricRegistry

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class SlidingWindowRateLimiter:
    def __init__(self, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.requests:
                retry_after = max(1, int(self.window_seconds - (timestamp - events[0])))
                return False, retry_after
            events.append(timestamp)
            return True, 0


def _harden(response, request_id: str, *, enforce_https: bool) -> None:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https:; "
        "style-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if enforce_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def install_operational_middleware(
    app: FastAPI,
    settings: object,
    registry: MetricRegistry,
) -> None:
    hosts = list(getattr(settings, "allowed_hosts"))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    limiter = SlidingWindowRateLimiter(
        int(getattr(settings, "rate_limit_requests")),
        int(getattr(settings, "rate_limit_window_seconds")),
    )
    logger = logging.getLogger("capital_intelligence.http")

    @app.middleware("http")
    async def operational_guard(request: Request, call_next):
        started = time.perf_counter()
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _REQUEST_ID.fullmatch(supplied) else str(uuid4())
        set_request_id(request_id)
        path = request.url.path
        client = request.client.host if request.client else "unknown"
        response = None
        try:
            if bool(getattr(settings, "enforce_https")):
                forwarded = request.headers.get("x-forwarded-proto", request.url.scheme)
                if forwarded.split(",", 1)[0].strip().lower() != "https":
                    response = JSONResponse(status_code=400, content={"detail": "HTTPS is required"})
            if response is None:
                content_length = request.headers.get("content-length")
                if content_length:
                    try:
                        length = int(content_length)
                    except ValueError:
                        response = JSONResponse(
                            status_code=400,
                            content={"detail": "invalid content-length"},
                        )
                    else:
                        if length > int(getattr(settings, "max_request_bytes")):
                            response = JSONResponse(
                                status_code=413,
                                content={"detail": "request body is too large"},
                            )
            if response is None and path not in {"/health", "/ready", "/live", "/metrics"}:
                allowed, retry_after = limiter.allow(client)
                if not allowed:
                    registry.increment("capital_intelligence_rate_limit_rejections_total")
                    response = JSONResponse(
                        status_code=429,
                        content={"detail": "rate limit exceeded"},
                        headers={"Retry-After": str(retry_after)},
                    )
            if response is None:
                response = await call_next(request)
            duration = time.perf_counter() - started
            registry.observe_request(request.method, path, response.status_code, duration)
            _harden(
                response,
                request_id,
                enforce_https=bool(getattr(settings, "enforce_https")),
            )
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                    "client": client,
                },
            )
            return response
        except Exception:
            registry.increment("capital_intelligence_unhandled_exceptions_total")
            logger.exception("unhandled request failure", extra={"method": request.method, "path": path})
            raise
        finally:
            set_request_id(None)


__all__ = ["SlidingWindowRateLimiter", "install_operational_middleware"]
