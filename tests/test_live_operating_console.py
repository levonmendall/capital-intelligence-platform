from __future__ import annotations

from datetime import datetime, timedelta, timezone

import live_operating_console
from provider_configuration import CredentialReadiness


class _Client:
    def account(self):
        return {"status": "ACTIVE"}

    def clock(self):
        now = datetime.now(timezone.utc)
        return {
            "is_open": True,
            "timestamp": (now - timedelta(seconds=1)).isoformat(),
        }

    def latest_quotes(self, symbols):
        now = datetime.now(timezone.utc)
        return {
            symbol: {
                "bp": 99.9,
                "ap": 100.1,
                "bs": 500,
                "as": 400,
                "t": (now - timedelta(seconds=2)).isoformat(),
            }
            for symbol in symbols
        }


def _configured_readiness() -> CredentialReadiness:
    return CredentialReadiness(
        provider="Alpaca",
        state="configured",
        detail="configured",
    )


def test_live_console_uses_all_provider_backed_pilot_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        live_operating_console,
        "alpaca_credential_readiness",
        _configured_readiness,
    )
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
    live_operating_console.load_live_market_console.clear()

    snapshot = live_operating_console.load_live_market_console()

    assert snapshot["status"] == "connected"
    assert snapshot["configuration_state"] == "configured"
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


def test_live_console_reports_missing_credentials_without_request(monkeypatch) -> None:
    monkeypatch.setattr(
        live_operating_console,
        "alpaca_credential_readiness",
        lambda: CredentialReadiness(
            provider="Alpaca",
            state="missing",
            detail="Missing Alpaca paper credentials.",
        ),
    )
    monkeypatch.setattr(
        live_operating_console.AlpacaPaperSettings,
        "from_env",
        classmethod(lambda cls: (_ for _ in ()).throw(AssertionError("must not run"))),
    )
    live_operating_console.load_live_market_console.clear()

    snapshot = live_operating_console.load_live_market_console()

    assert snapshot["status"] == "unavailable"
    assert snapshot["configuration_state"] == "missing"
    assert snapshot["quote_count"] == 0
    assert snapshot["rows"] == []
    assert "Missing Alpaca" in snapshot["detail"]
    assert snapshot["real_money_authorized"] is False


def test_live_console_sanitizes_provider_authentication_failure(monkeypatch) -> None:
    def unavailable(_cls):
        raise ValueError("Alpaca returned HTTP 401 with secret-value")

    monkeypatch.setattr(
        live_operating_console,
        "alpaca_credential_readiness",
        _configured_readiness,
    )
    monkeypatch.setattr(
        live_operating_console.AlpacaPaperSettings,
        "from_env",
        classmethod(unavailable),
    )
    live_operating_console.load_live_market_console.clear()

    snapshot = live_operating_console.load_live_market_console()

    assert snapshot["status"] == "unavailable"
    assert snapshot["configuration_state"] == "invalid"
    assert "HTTP 401" in snapshot["detail"]
    assert "secret-value" not in snapshot["detail"]


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
