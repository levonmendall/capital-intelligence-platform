from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.routes import cio_diagnostic
from providers.databento_options import DatabentoOptionsError, DatabentoOptionsProvider

AS_OF = datetime(2026, 8, 11, 16, 50, tzinfo=timezone.utc)


class _Response:
    def __init__(self, *, status_code: int = 200, records=(), detail: str | None = None):
        self.status_code = status_code
        values = list(records)
        if detail is not None:
            values.append({"detail": detail})
        self.text = "\n".join(json.dumps(item) for item in values)


def _definition_record() -> dict[str, object]:
    return {
        "symbol": "SPY   261218C00620000",
        "raw_symbol": "SPY   261218C00620000",
        "hd": {"instrument_id": 101},
        "asset": "SPY",
        "underlying": "SPY",
        "instrument_class": "C",
        "expiration": "2026-12-18T00:00:00.000000000Z",
        "strike_price": "620.000000000",
        "contract_multiplier": "100",
    }


def test_nonretryable_databento_http_error_fails_immediately() -> None:
    calls: list[dict[str, object]] = []

    def post(_url, **kwargs):
        calls.append(kwargs)
        return _Response(status_code=403, detail="not entitled")

    provider = DatabentoOptionsProvider(api_key="secret", http_post=post)
    with pytest.raises(DatabentoOptionsError, match="HTTP 403") as captured:
        provider.definitions("SPY", as_of=AS_OF)

    assert len(calls) == 1
    assert captured.value.status_code == 403
    assert captured.value.retryable is False
    assert "secret" not in str(captured.value)


def test_transient_databento_failure_retries_prior_session() -> None:
    calls: list[dict[str, object]] = []

    def post(_url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _Response(status_code=503, detail="provider temporarily unavailable")
        return _Response(records=(_definition_record(),))

    provider = DatabentoOptionsProvider(api_key="secret", http_post=post)
    definitions = provider.definitions("SPY", as_of=AS_OF)

    assert len(calls) == 2
    assert definitions
    assert definitions[0].underlying == "SPY"


def test_databento_default_request_and_session_retry_budget_is_bounded() -> None:
    calls: list[dict[str, object]] = []

    def post(_url, **kwargs):
        calls.append(kwargs)
        return _Response(status_code=503, detail="provider temporarily unavailable")

    provider = DatabentoOptionsProvider(api_key="secret", http_post=post)
    with pytest.raises(DatabentoOptionsError, match="definitions unavailable"):
        provider.definitions("SPY", as_of=AS_OF)

    assert len(calls) == 4
    assert {call["timeout"] for call in calls} == {15}


def test_diagnostic_reports_render_comprehensive_requirement_before_context_exists(
    monkeypatch,
) -> None:
    diagnostic = SimpleNamespace(
        state="in_progress",
        detail="production context is being prepared",
        requested_by="render-release:release-sha",
        request_id="diagnostic-1",
        requested_at=AS_OF,
        started_at=AS_OF,
        completed_at=None,
        progress_stage="catalog_databento_options",
        cycle_key="cycle-1",
        snapshot_identifier=None,
    )
    monkeypatch.setattr(
        cio_diagnostic,
        "latest_manual_cio_diagnostic",
        lambda *, values: diagnostic,
    )
    monkeypatch.setattr(cio_diagnostic, "_state_path", lambda _settings: Path("unused"))
    monkeypatch.setattr(cio_diagnostic, "_load_json", lambda _path: {})
    monkeypatch.setattr(cio_diagnostic, "_latest_context_attempt", lambda _settings: {})

    audit = cio_diagnostic.build_cio_diagnostic_audit(
        settings=SimpleNamespace(),
        values={
            "CAPITAL_INTELLIGENCE_RELEASE": "release-sha",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
        },
    )

    assert audit["comprehensive_discovery_required"] is True
    assert audit["comprehensive_discovery_complete"] is False
    assert audit["all_market_evaluation_complete"] is False
    assert audit["ready"] is False
