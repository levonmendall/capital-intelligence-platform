from __future__ import annotations

from datetime import datetime, timedelta, timezone

import live_operating_console


NOW = datetime(2026, 7, 29, 13, 30, tzinfo=timezone.utc)


class _Client:
    def account(self):
        return {"status": "ACTIVE"}

    def clock(self):
        return {"is_open": True, "timestamp": (NOW - timedelta(seconds=1)).isoformat()}

    def latest_quotes(self, symbols):
        return {
            symbol: {
                "bp": 99.9,
                "ap": 100.1,
                "bs": 500,
                "as": 400,
                "t": (NOW - timedelta(seconds=2)).isoformat(),
            }
            for symbol in symbols
        }


def test_live_console_uses_all_provider_backed_pilot_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        live_operating_console.AlpacaPaperSettings,
        "from_env",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        live_operating_console,
        "AlpacaPaperClient",
        lambda _settings: _Client(),
    )
    monkeypatch.setattr(
        live_operating_console,
        "datetime",
        type(
            "_DateTime",
            (),
            {"now": staticmethod(lambda _tz: NOW)},
        ),
    )
    live_operating_console.load_live_market_console.clear()

    snapshot = live_operating_console.load_live_market_console()

    assert snapshot["status"] == "connected"
    assert snapshot["account_status"] == "ACTIVE"
    assert snapshot["market_open"] is True
    assert snapshot["quote_count"] == 15
    assert snapshot["expected_quote_count"] == 15
    assert snapshot["paper_only"] is True
    assert snapshot["real_money_authorized"] is False
    rows = snapshot["rows"]
    assert isinstance(rows, list)
    assert {item["symbol"] for item in rows} == {
        "VTI",
        "VXUS",
        "GOVT",
        "LQD",
        "HYG",
        "SGOV",
        "DBC",
        "GLD",
        "UUP",
        "IBIT",
        "VNQ",
        "DBMF",
        "WTPI",
        "VIXY",
        "BTAL",
    }
    assert all(item["mid"] == 100.0 for item in rows)
    assert all(item["current"] is True for item in rows)


def test_live_console_reports_unavailable_without_substituting_values(monkeypatch) -> None:
    def unavailable(_cls):
        raise ValueError("paper credentials unavailable")

    monkeypatch.setattr(
        live_operating_console.AlpacaPaperSettings,
        "from_env",
        classmethod(unavailable),
    )
    live_operating_console.load_live_market_console.clear()

    snapshot = live_operating_console.load_live_market_console()

    assert snapshot["status"] == "unavailable"
    assert snapshot["quote_count"] == 0
    assert snapshot["rows"] == []
    assert "credentials unavailable" in snapshot["detail"]
    assert snapshot["real_money_authorized"] is False


def test_app_wires_all_four_surfaces_to_live_refresh_and_reports() -> None:
    source = open("app.py", encoding="utf-8").read()

    for surface in (
        "_render_today",
        "_render_environment",
        "_render_portfolio",
        "_render_history",
    ):
        assert surface in source
    assert '@st.fragment(run_every="30s")' in source
    assert "render_live_market_status(" in source
    assert "render_live_environment_market_table(" in source
    assert "render_live_portfolio_marks(" in source
    assert "render_operating_report_history(" in source
    assert "render_pending_transaction_report(" in source
