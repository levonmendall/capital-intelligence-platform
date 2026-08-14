from __future__ import annotations

from pathlib import Path

import verify_render_cio_diagnostic as verifier
from providers.massive_futures_reference import MassiveFuturesReferenceProvider


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self) -> object:
        return self._payload


def _contract(product_code: str, ticker: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "product_code": product_code,
        "trading_venue": "XCME",
        "first_trade_date": "2026-01-01",
        "last_trade_date": "2026-12-18",
        "settlement_date": "2026-12-18",
        "active": True,
    }


def test_futures_reference_queries_only_configured_roots_and_paces_calls() -> None:
    calls: list[dict[str, object]] = []
    sleeps: list[float] = []

    def get(_url: str, *, params: dict[str, object], timeout: int) -> _Response:
        assert timeout > 0
        calls.append(dict(params))
        product = str(params.get("product_code") or "")
        ticker = {"ES": "ESZ26", "NQ": "NQZ26"}[product]
        return _Response({"status": "OK", "results": [_contract(product, ticker)]})

    provider = MassiveFuturesReferenceProvider(
        "test-key",
        minimum_call_interval_seconds=12.5,
        http_get=get,
        sleeper=sleeps.append,
    )

    contracts = provider.futures_contracts(
        as_of=verifier.datetime(2026, 8, 13, tzinfo=verifier.timezone.utc)
        if hasattr(verifier, "datetime")
        else __import__("datetime").datetime(2026, 8, 13, tzinfo=__import__("datetime").timezone.utc),
        product_codes=("ES", "NQ"),
    )

    assert [item.product_code for item in contracts] == ["ES", "NQ"]
    assert [call["product_code"] for call in calls] == ["ES", "NQ"]
    assert all("product_code" in call for call in calls)
    assert sleeps == [12.5]


def test_futures_reference_429_waits_for_rate_window_before_retry() -> None:
    responses = iter(
        (
            _Response({}, status_code=429),
            _Response({"status": "OK", "results": [_contract("ES", "ESZ26")]}),
        )
    )
    sleeps: list[float] = []

    provider = MassiveFuturesReferenceProvider(
        "test-key",
        minimum_call_interval_seconds=0,
        rate_limit_retry_seconds=60,
        reference_max_attempts=2,
        http_get=lambda *_args, **_kwargs: next(responses),
        sleeper=sleeps.append,
    )

    from datetime import datetime, timezone

    contracts = provider.futures_contracts(
        as_of=datetime(2026, 8, 13, tzinfo=timezone.utc),
        product_codes=("ES",),
    )

    assert [item.ticker for item in contracts] == ["ESZ26"]
    assert sleeps == [60.0]


def _audit_payload(
    release: str,
    *,
    request_id: str,
    state: str,
) -> dict[str, object]:
    completed = state in {"completed", "failed"}
    successful = state == "completed"
    return {
        "schema_version": "public-cio-diagnostic-audit.v1",
        "credential_safe": True,
        "active_release": release,
        "release_matches": True,
        "request_id": request_id,
        "state": state,
        "completed_at": "2026-08-14T00:00:00+00:00" if completed else None,
        "ready": successful,
        "context_cycle_matches": successful,
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_complete": successful,
        "scheduled_market_coverage_complete": successful,
        "terminal_screening_complete": successful,
        "all_market_evaluation_complete": successful,
        "market_lanes": (
            [
                {
                    "asset_class": "future",
                    "scheduled": True,
                    "represented": True,
                    "catalog_count": 1,
                    "deep_analyzed_count": 1,
                    "selected_count": 1,
                }
            ]
            if successful
            else []
        ),
        "detail": "Massive returned HTTP 429" if state == "failed" else None,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_verifier_waits_through_adopted_failure_for_replacement_attempt(
    tmp_path: Path,
) -> None:
    release = "release-current"
    payloads = iter(
        (
            _audit_payload(release, request_id="attempt-a", state="in_progress"),
            _audit_payload(release, request_id="attempt-a", state="failed"),
            _audit_payload(release, request_id="attempt-b", state="in_progress"),
            _audit_payload(release, request_id="attempt-b", state="completed"),
        )
    )
    sleeps: list[float] = []
    progress: list[str] = []

    result = verifier.poll_render_audit(
        url="https://example.test/app/static/cio-diagnostic.json",
        expected_release=release,
        output_path=tmp_path / "audit.json",
        maximum_attempts=4,
        interval_seconds=0,
        fetcher=lambda _url: next(payloads),
        sleeper=sleeps.append,
        progress_writer=progress.append,
    )

    assert result["request_id"] == "attempt-b"
    assert result["state"] == "completed"
    assert any("awaiting_replacement_attempt" in item for item in progress)
