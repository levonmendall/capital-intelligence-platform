from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations.free_paper_pilot import load_free_paper_pilot_universe
from providers.alpaca_paper import (
    AlpacaPaperQuoteProvider,
    AlpacaPaperSessionProvider,
    AlpacaPaperSettings,
)
from governance import TradingSessionModel


class _Client:
    settings = AlpacaPaperSettings(
        api_key_id="paper-key",
        secret_key="paper-secret",
    )

    def __init__(self, *, timestamp: datetime) -> None:
        self.timestamp = timestamp

    def clock(self):
        return {"timestamp": self.timestamp.isoformat(), "is_open": True}

    def asset(self, _symbol):
        return {"status": "active", "tradable": True, "fractionable": True}

    def latest_quotes(self, symbols):
        return {
            symbol: {
                "bp": 100.0,
                "ap": 100.1,
                "bs": 100.0,
                "as": 100.0,
                "t": self.timestamp.isoformat(),
            }
            for symbol in symbols
        }


def test_alpaca_execution_adapters_tolerate_small_provider_clock_skew() -> None:
    as_of = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    client = _Client(timestamp=as_of + timedelta(seconds=2))
    profile = load_free_paper_pilot_universe().profiles()[0]

    session = AlpacaPaperSessionProvider(client).session(
        profile,
        session_model=TradingSessionModel.EXCHANGE_LOCAL,
        as_of=as_of,
    )
    quote = AlpacaPaperQuoteProvider(client).quotes((profile,), as_of=as_of)[profile.symbol]

    assert session.as_of == as_of
    assert quote.observed_at == as_of
    assert quote.fx_observed_at == as_of


def test_alpaca_execution_adapters_reject_material_future_evidence() -> None:
    as_of = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    client = _Client(timestamp=as_of + timedelta(seconds=6))
    profile = load_free_paper_pilot_universe().profiles()[0]

    try:
        AlpacaPaperSessionProvider(client).session(
            profile,
            session_model=TradingSessionModel.EXCHANGE_LOCAL,
            as_of=as_of,
        )
    except RuntimeError as error:
        assert "future-known" in str(error)
    else:
        raise AssertionError("material future clock evidence must be rejected")
