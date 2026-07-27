from __future__ import annotations

from datetime import datetime, timezone

import pytest

from providers.fred import FREDObservation, FREDProviderError
from run_fred_live_smoke import build_live_fred_report, safe_failure_report


class _ConfiguredProvider:
    name = "FRED"
    configured = True

    def get_observations(
        self,
        series_id: str,
        limit: int = 24,
        sort_order: str = "desc",
    ) -> list[FREDObservation]:
        assert series_id == "DGS10"
        assert limit == 3
        assert sort_order == "desc"
        return [
            FREDObservation(date="2026-07-24", value=4.23),
            FREDObservation(date="2026-07-23", value=4.21),
        ]


class _UnconfiguredProvider(_ConfiguredProvider):
    configured = False


def test_live_report_proves_access_without_disclosing_secret() -> None:
    report = build_live_fred_report(
        _ConfiguredProvider(),
        series_id="dgs10",
        checked_at=datetime(2026, 7, 27, 23, 30, tzinfo=timezone.utc),
    )

    assert report["state"] == "ready"
    assert report["series_id"] == "DGS10"
    assert report["latest_observation_date"] == "2026-07-24"
    assert report["observation_count"] == 2
    assert report["credential_environment_variable"] == "FRED_API_KEY"
    assert report["credential_configured"] is True
    assert report["secret_disclosed"] is False
    assert "api_key" not in report
    assert "value" not in report


def test_unconfigured_provider_fails_closed() -> None:
    with pytest.raises(FREDProviderError, match="FRED_API_KEY"):
        build_live_fred_report(
            _UnconfiguredProvider(),
            series_id="DGS10",
        )


def test_failure_report_does_not_serialize_sensitive_exception_text() -> None:
    error = RuntimeError("request failed with api_key=do-not-disclose")
    report = safe_failure_report(
        series_id="DGS10",
        error=error,
        checked_at=datetime(2026, 7, 27, 23, 30, tzinfo=timezone.utc),
    )

    serialized = str(report)
    assert report["state"] == "blocked"
    assert report["error_type"] == "RuntimeError"
    assert report["secret_disclosed"] is False
    assert "do-not-disclose" not in serialized
