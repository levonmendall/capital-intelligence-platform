from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cio import CandidateAssetClass
from governance import TradingSessionModel
from operations.direct_global_markets import (
    DirectGlobalMarketClient,
    DirectPaperQuoteProvider,
    DirectPaperSessionProvider,
    load_direct_global_market_universe,
)
from portfolio.multi_asset_execution import InstrumentSessionStatus


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def json(self) -> Any:
        return self.payload


def _chart_payload(prices: tuple[float, ...]) -> dict[str, object]:
    timestamps = tuple(
        int((NOW - timedelta(days=len(prices) - index - 1)).timestamp())
        for index in range(len(prices))
    )
    return {
        "chart": {
            "result": [
                {
                    "timestamp": list(timestamps),
                    "indicators": {
                        "quote": [
                            {
                                "close": list(prices),
                                "volume": [1_000_000] * len(prices),
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _http_get(url: str, **_kwargs: Any) -> _Response:
    if "BTC-USD" in url:
        return _Response(_chart_payload((60_000.0, 61_000.0, 62_000.0)))
    if "EURUSD" in url:
        return _Response(_chart_payload((1.08, 1.09, 1.10)))
    return _Response(_chart_payload((5_000.0, 5_050.0, 5_100.0)))


def test_direct_universe_contains_first_class_fx_crypto_and_futures() -> None:
    universe = load_direct_global_market_universe(
        ROOT / "config" / "direct_global_market_universe.json"
    )

    classes = {item.execution_asset_class for item in universe.instruments}
    assert classes == {
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
    }
    assert all(item.provider_symbol for item in universe.instruments)
    assert all(item.maximum_weight > 0 for item in universe.instruments)
    assert not universe.schema_version.endswith("wrapper")


def test_direct_profiles_enforce_spot_and_fully_collateralized_contract_models() -> None:
    universe = load_direct_global_market_universe(
        ROOT / "config" / "direct_global_market_universe.json"
    )
    profiles = {
        item.symbol: item.profile(universe_identifier=universe.identifier)
        for item in universe.instruments
    }

    assert profiles["EURUSD"].unlevered
    assert profiles["EURUSD"].spot_only
    assert profiles["EURUSD"].trading_session_model is TradingSessionModel.CONTINUOUS_24_5
    assert profiles["BTCUSD"].unlevered
    assert profiles["BTCUSD"].spot_only
    assert profiles["BTCUSD"].trading_session_model is TradingSessionModel.CONTINUOUS_24_7
    assert not profiles["ES1"].spot_only
    assert profiles["ES1"].gross_leverage == 1.0
    assert profiles["ES1"].defined_risk
    assert profiles["ES1"].contract_multiplier == 50.0
    assert profiles["ES1"].contract_model_version
    assert profiles["ES1"].margin_model_version
    assert profiles["ES1"].lifecycle_model_version
    assert profiles["ES1"].roll_model_version


def test_direct_public_evidence_normalizes_to_canonical_bars_quotes_and_sessions() -> None:
    universe = load_direct_global_market_universe(
        ROOT / "config" / "direct_global_market_universe.json"
    )
    selected = tuple(
        item for item in universe.instruments
        if item.symbol in {"EURUSD", "BTCUSD", "ES1"}
    )
    client = DirectGlobalMarketClient(
        type(universe)(
            identifier=universe.identifier,
            provider_identifier=universe.provider_identifier,
            instruments=selected,
            limitations=universe.limitations,
        ),
        http_get=_http_get,
    )

    bars = client.historical_bars(
        ("EURUSD", "BTCUSD", "ES1"),
        start=NOW - timedelta(days=30),
        end=NOW + timedelta(days=1),
    )
    quotes = client.latest_quotes(("EURUSD", "BTCUSD", "ES1"))
    snapshots = client.snapshots(("EURUSD", "BTCUSD", "ES1"))

    assert all(len(items) == 3 for items in bars.values())
    assert all(item["ap"] > item["bp"] > 0 for item in quotes.values())
    assert all("prevDailyBar" in item for item in snapshots.values())

    profile_map = {
        item.symbol: item.profile(universe_identifier=universe.identifier)
        for item in selected
    }
    session_provider = DirectPaperSessionProvider(client)
    quote_provider = DirectPaperQuoteProvider(client)
    crypto_session = session_provider.session(
        profile_map["BTCUSD"],
        session_model=TradingSessionModel.CONTINUOUS_24_7,
        as_of=NOW,
    )
    paper_quotes = quote_provider.quotes(tuple(profile_map.values()), as_of=NOW)

    assert crypto_session.status is InstrumentSessionStatus.OPEN
    assert set(paper_quotes) == set(profile_map)
    assert all(
        item.quote_certification_identifier.startswith("direct-paper-quote:")
        for item in paper_quotes.values()
    )
    assert all(item.fx_rate_to_base == 1.0 for item in paper_quotes.values())


def test_blanket_direct_market_prohibition_is_removed() -> None:
    static_payload = json.loads(
        (ROOT / "config" / "free_paper_pilot_universe.json").read_text(
            encoding="utf-8"
        )
    )
    free_source = (ROOT / "operations" / "free_paper_pilot.py").read_text(
        encoding="utf-8"
    )

    assert "direct_instrument_classes_prohibited" not in static_payload
    assert "direct_instrument_classes_prohibited" not in free_source
    assert "Direct futures, options, bonds, FX, crypto tokens" not in free_source
