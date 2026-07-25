"""Operational hardening contract tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations import (
    MetricRegistry,
    OperationalSettings,
    SlidingWindowRateLimiter,
    WorkerHeartbeatStore,
)


def test_production_settings_require_https_metrics_and_encrypted_backups() -> None:
    with pytest.raises(ValueError, match="enforce_https"):
        OperationalSettings(environment="production")

    settings = OperationalSettings.from_env(
        {
            "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
            "CAPITAL_INTELLIGENCE_ENFORCE_HTTPS": "true",
            "CAPITAL_INTELLIGENCE_ALLOWED_HOSTS": "api.example.com",
            "CAPITAL_INTELLIGENCE_METRICS_TOKEN": "m" * 32,
            "CAPITAL_INTELLIGENCE_REQUIRE_ENCRYPTED_BACKUPS": "true",
            "CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY": "x" * 44,
        }
    )
    assert settings.environment == "production"
    assert settings.allowed_hosts == ("api.example.com",)


def test_rate_limiter_resets_after_window() -> None:
    limiter = SlidingWindowRateLimiter(2, 10)
    assert limiter.allow("client", now=0)[0]
    assert limiter.allow("client", now=1)[0]
    allowed, retry_after = limiter.allow("client", now=2)
    assert not allowed
    assert retry_after >= 1
    assert limiter.allow("client", now=11)[0]


def test_metrics_render_prometheus_labels() -> None:
    registry = MetricRegistry()
    registry.observe_request("GET", "/health", 200, 0.25)
    output = registry.render()
    assert "capital_intelligence_http_requests_total" in output
    assert 'method="GET"' in output
    assert 'status="200"' in output
    assert "capital_intelligence_http_request_duration_seconds_sum" in output


def test_worker_heartbeat_detects_stale_and_failed_states(tmp_path) -> None:
    store = WorkerHeartbeatStore(tmp_path / "worker.json")
    now = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
    store.write("healthy", observed_at=now, cycle_key="daily:2026-07-25")
    healthy, _, _ = store.health(maximum_age_seconds=120, now=now + timedelta(seconds=60))
    assert healthy
    stale, detail, _ = store.health(maximum_age_seconds=120, now=now + timedelta(seconds=121))
    assert not stale
    assert "stale" in detail
    store.write("failed", observed_at=now, detail="provider unavailable")
    failed, detail, _ = store.health(maximum_age_seconds=120, now=now)
    assert not failed
    assert detail == "provider unavailable"


def test_operational_middleware_adds_request_ids_and_limits_large_bodies() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from operations import install_operational_middleware

    app = FastAPI()
    registry = MetricRegistry()
    settings = OperationalSettings(max_request_bytes=1024)
    install_operational_middleware(app, settings, registry)

    @app.post("/echo")
    def echo() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    accepted = client.post("/echo", headers={"X-Request-ID": "request-123"})
    rejected = client.post("/echo", content=b"x" * 1025)

    assert accepted.status_code == 200
    assert accepted.headers["x-request-id"] == "request-123"
    assert accepted.headers["x-content-type-options"] == "nosniff"
    assert rejected.status_code == 413
    assert "capital_intelligence_http_requests_total" in registry.render()
