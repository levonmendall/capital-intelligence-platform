from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from production_context_publication_governed import (
    prepare_governed_production_context_for_cycle,
)
from providers.eodhd import EODHDRetrievalFailure
from tests.test_production_context_publication_runtime import (
    _bootstrap_cash_portfolio,
    _equity_discovery_probe,
    _evidence,
    _readiness,
    _settings,
)


def _unentitled_lse(**_kwargs):
    raise EODHDRetrievalFailure(
        resource="active symbol directory LSE",
        category="http_client_error",
        retryable=False,
        status_code=402,
    )


def test_optional_unentitled_global_directory_does_not_discard_us_search(tmp_path) -> None:
    settings = _settings(tmp_path)
    scheduled_for = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
    decision_time = datetime(2026, 8, 3, 14, 5, tzinfo=timezone.utc)
    _bootstrap_cash_portfolio(
        settings,
        as_of=datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc),
    )

    result = prepare_governed_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=lambda _universe: _readiness(decision_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-31", value=4.25),
        evidence_probe=lambda _universe, _as_of: _evidence(decision_time),
        equity_discovery_probe=_equity_discovery_probe,
        comprehensive_discovery_probe=_unentitled_lse,
        comprehensive_discovery_required=False,
        clock=lambda: decision_time,
    )

    assert result.ready is True
    assert result.candidate_count == 15
    assert "does not claim complete all-market coverage" in result.detail
    state = json.loads(
        (tmp_path / "production-context-publication-state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["comprehensive_discovery_scope_state"] == "optional_unavailable"
    assert state["comprehensive_discovery_required"] is False
    assert any(
        "HTTP 402" in item
        for item in state["comprehensive_discovery_limitations"]
    )


def test_required_unentitled_global_directory_remains_fail_closed(tmp_path) -> None:
    settings = _settings(tmp_path)
    scheduled_for = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
    decision_time = datetime(2026, 8, 3, 14, 5, tzinfo=timezone.utc)
    _bootstrap_cash_portfolio(
        settings,
        as_of=datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc),
    )

    result = prepare_governed_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=lambda _universe: _readiness(decision_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-31", value=4.25),
        evidence_probe=lambda _universe, _as_of: _evidence(decision_time),
        equity_discovery_probe=_equity_discovery_probe,
        comprehensive_discovery_probe=_unentitled_lse,
        comprehensive_discovery_required=True,
        clock=lambda: decision_time,
    )

    assert result.state == "blocked"
    assert "Required certified comprehensive market discovery" in result.detail
    assert "HTTP 402" in result.detail
