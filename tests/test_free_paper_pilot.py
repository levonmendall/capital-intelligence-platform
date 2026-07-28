"""Regression coverage for the constrained free-data paper pilot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cio import CandidateAssetClass
from operations.free_paper_pilot import (
    assess_free_paper_pilot_readiness,
    load_free_paper_pilot_universe,
    validate_pilot_construction,
)
from portfolio.multi_asset_execution import MultiAssetExecutionPolicy
from providers.alpaca_paper import (
    AlpacaPaperClient,
    AlpacaPaperProviderError,
    AlpacaPaperQuoteProvider,
    AlpacaPaperSettings,
    create_alpaca_paper_client,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


def _http_get(url: str, **kwargs: Any) -> _Response:
    if url.endswith("/v2/account"):
        return _Response(
            {
                "status": "ACTIVE",
                "trading_blocked": False,
                "account_blocked": False,
            }
        )
    if url.endswith("/v2/clock"):
        return _Response(
            {
                "is_open": True,
                "timestamp": (NOW - timedelta(seconds=2)).isoformat(),
            }
        )
    if "/v2/assets/" in url:
        symbol = url.rsplit("/", 1)[-1]
        return _Response(
            {
                "symbol": symbol,
                "status": "active",
                "tradable": True,
                "fractionable": True,
                "class": "us_equity",
            }
        )
    if url.endswith("/v2/stocks/quotes/latest"):
        symbols = str(kwargs["params"]["symbols"]).split(",")
        return _Response(
            {
                "quotes": {
                    symbol: {
                        "bp": 99.9,
                        "ap": 100.1,
                        "bs": 500,
                        "as": 400,
                        "t": (NOW - timedelta(seconds=3)).isoformat(),
                    }
                    for symbol in symbols
                }
            }
        )
    raise AssertionError(f"unexpected URL {url}")


def _client() -> AlpacaPaperClient:
    return AlpacaPaperClient(
        AlpacaPaperSettings(
            api_key_id="paper-key",
            secret_key="paper-secret",
        ),
        http_get=_http_get,
    )


def test_free_pilot_has_exact_broad_exposure_and_no_direct_complex_assets() -> None:
    universe = load_free_paper_pilot_universe(
        ROOT / "config" / "free_paper_pilot_universe.json"
    )

    assert len(universe.instruments) == 15
    assert set(universe.required_exposure_classes) == {
        item.economic_exposure for item in universe.instruments
    }
    assert all(
        item.execution_asset_class
        in {
            CandidateAssetClass.US_EQUITY,
            CandidateAssetClass.US_ETF,
            CandidateAssetClass.CASH_EQUIVALENT,
        }
        for item in universe.instruments
    )
    assert "future_contract" in universe.direct_instrument_classes_prohibited
    assert "option_contract" in universe.direct_instrument_classes_prohibited
    assert universe.instrument_for_exposure("crypto").maximum_weight == pytest.approx(0.05)
    assert universe.instrument_for_exposure("volatility").maximum_weight == pytest.approx(0.02)


def test_core_listed_profiles_are_supported_by_canonical_paper_execution() -> None:
    universe = load_free_paper_pilot_universe(
        ROOT / "config" / "free_paper_pilot_universe.json"
    )
    profiles = universe.profiles()
    policy = MultiAssetExecutionPolicy()

    assert len(profiles) == len(universe.instruments)
    assert policy.version == "multi-asset-paper-execution.v2"
    assert policy.commission_bps(CandidateAssetClass.US_ETF) == 0.0
    assert policy.fractional_quantity(CandidateAssetClass.US_ETF, "fund")
    assert all(profile.gross_leverage == 1.0 for profile in profiles)
    assert all(not profile.margin_required for profile in profiles)


def test_live_broker_endpoint_is_rejected_for_free_pilot(monkeypatch) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")

    with pytest.raises(AlpacaPaperProviderError, match="paper endpoint"):
        AlpacaPaperSettings.from_env()


def test_readiness_validates_account_assets_and_current_iex_quotes() -> None:
    universe = load_free_paper_pilot_universe(
        ROOT / "config" / "free_paper_pilot_universe.json"
    )

    report = assess_free_paper_pilot_readiness(
        universe=universe,
        client=_client(),
        evaluated_at=NOW,
    )

    assert report.configuration_ready
    assert report.execution_ready_now
    assert report.market_open
    assert report.account_status == "ACTIVE"
    assert len(report.validated_symbols) == 15
    assert not report.blockers
    assert not report.real_money_authorized


def test_quote_provider_emits_canonical_certified_paper_quotes() -> None:
    universe = load_free_paper_pilot_universe(
        ROOT / "config" / "free_paper_pilot_universe.json"
    )
    profiles = universe.profiles()[:2]

    quotes = AlpacaPaperQuoteProvider(_client()).quotes(profiles, as_of=NOW)

    assert set(quotes) == {profile.symbol for profile in profiles}
    assert all(item.ask >= item.bid for item in quotes.values())
    assert all(item.fx_rate_to_base == 1.0 for item in quotes.values())
    assert all("free-paper-pilot-quote" in item.quote_certification_identifier for item in quotes.values())


def test_pilot_construction_enforces_scope_cash_turnover_and_symbol_limits() -> None:
    universe = load_free_paper_pilot_universe(
        ROOT / "config" / "free_paper_pilot_universe.json"
    )
    valid = {
        "status": "ready",
        "turnover": 0.05,
        "target_cash_weight": 0.80,
        "target_weights": [{"symbol": "VTI", "weight": 0.20}],
        "trades": [{"symbol": "VTI", "side": "buy"}],
        "blocks": [],
    }

    validate_pilot_construction(valid, universe=universe)

    with pytest.raises(ValueError, match="outside the free pilot"):
        validate_pilot_construction(
            {
                **valid,
                "trades": [{"symbol": "ESU6", "side": "buy"}],
            },
            universe=universe,
        )
    with pytest.raises(ValueError, match="below"):
        validate_pilot_construction(
            {
                **valid,
                "target_cash_weight": 0.10,
                "target_weights": [{"symbol": "VTI", "weight": 0.20}],
            },
            universe=universe,
        )


def test_free_pilot_contains_no_broker_order_submission_path() -> None:
    provider_source = (ROOT / "providers" / "alpaca_paper.py").read_text(
        encoding="utf-8"
    )
    runner_source = (ROOT / "run_free_paper_pilot.py").read_text(
        encoding="utf-8"
    )

    assert "/v2/orders" not in provider_source
    assert "development-only" in runner_source
    assert "--development-bypass-launch-gate" in runner_source
    assert "run_approved_paper_execution" in runner_source

def test_common_alpaca_environment_aliases_are_supported(monkeypatch) -> None:
    for name in (
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "APCA_API_BASE_URL",
        "APCA_DATA_BASE_URL",
        "APCA_DATA_FEED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "alias-paper-key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "alias-paper-secret")
    monkeypatch.setenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")
    monkeypatch.setenv("ALPACA_DATA_FEED", "iex")

    settings = AlpacaPaperSettings.from_env()

    assert settings.api_key_id == "alias-paper-key"
    assert settings.secret_key == "alias-paper-secret"
    assert settings.paper_base_url == "https://paper-api.alpaca.markets"
    assert settings.data_base_url == "https://data.alpaca.markets"
    assert settings.data_feed == "iex"

def test_authenticated_pair_selection_uses_matching_credentials(monkeypatch) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "wrong-key")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "matching-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "wrong-secret")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "matching-secret")

    attempts: list[tuple[str, str]] = []

    def authenticated_get(url: str, **kwargs: Any) -> _Response:
        headers = kwargs["headers"]
        pair = (headers["APCA-API-KEY-ID"], headers["APCA-API-SECRET-KEY"])
        attempts.append(pair)
        if pair == ("matching-key", "matching-secret") and url.endswith("/v2/account"):
            return _Response({"status": "ACTIVE"})
        return _Response({"message": "unauthorized"}, status_code=401)

    client = create_alpaca_paper_client(http_get=authenticated_get)

    assert client.settings.api_key_id == "matching-key"
    assert client.settings.secret_key == "matching-secret"
    assert attempts[-1] == ("matching-key", "matching-secret")
    assert len(attempts) == 4

def test_live_readiness_uses_post_response_time_for_quote_cutoff() -> None:
    def current_quote_http_get(url: str, **kwargs: Any) -> _Response:
        if url.endswith("/v2/stocks/quotes/latest"):
            symbols = str(kwargs["params"]["symbols"]).split(",")
            observed = datetime.now(timezone.utc).isoformat()
            return _Response(
                {
                    "quotes": {
                        symbol: {
                            "bp": 99.9,
                            "ap": 100.1,
                            "bs": 500,
                            "as": 400,
                            "t": observed,
                        }
                        for symbol in symbols
                    }
                }
            )
        return _http_get(url, **kwargs)

    universe = load_free_paper_pilot_universe(
        ROOT / "config" / "free_paper_pilot_universe.json"
    )
    client = AlpacaPaperClient(
        AlpacaPaperSettings(api_key_id="paper-key", secret_key="paper-secret"),
        http_get=current_quote_http_get,
    )

    report = assess_free_paper_pilot_readiness(universe=universe, client=client)

    assert report.configuration_ready
    assert len(report.quote_timestamps) == 15
    assert not any("future-known" in blocker for blocker in report.blockers)

def test_closed_market_zero_top_of_book_holds_execution_without_blocking_configuration() -> None:
    def closed_market_http_get(url: str, **kwargs: Any) -> _Response:
        if url.endswith("/v2/clock"):
            return _Response(
                {
                    "is_open": False,
                    "timestamp": (NOW - timedelta(seconds=2)).isoformat(),
                }
            )
        if url.endswith("/v2/stocks/quotes/latest"):
            symbols = str(kwargs["params"]["symbols"]).split(",")
            return _Response(
                {
                    "quotes": {
                        symbol: {
                            "bp": 0.0,
                            "ap": 0.0,
                            "bs": 0,
                            "as": 0,
                            "t": (NOW - timedelta(seconds=3)).isoformat(),
                        }
                        for symbol in symbols
                    }
                }
            )
        return _http_get(url, **kwargs)

    universe = load_free_paper_pilot_universe(
        ROOT / "config" / "free_paper_pilot_universe.json"
    )
    client = AlpacaPaperClient(
        AlpacaPaperSettings(api_key_id="paper-key", secret_key="paper-secret"),
        http_get=closed_market_http_get,
    )

    report = assess_free_paper_pilot_readiness(
        universe=universe,
        client=client,
        evaluated_at=NOW,
    )

    assert report.configuration_ready
    assert not report.execution_ready_now
    assert not report.market_open
    assert len(report.quote_timestamps) == 15
    assert any("closed-market IEX top of book" in warning for warning in report.warnings)

