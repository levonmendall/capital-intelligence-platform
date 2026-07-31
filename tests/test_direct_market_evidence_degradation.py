from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import production_paper_evidence as evidence
from operations.direct_global_markets import load_direct_global_market_universe
from operations.free_paper_pilot import load_free_paper_pilot_universe


NOW = datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc)


class _AlpacaClient:
    def historical_bars(self, symbols, **_kwargs):
        return {symbol: () for symbol in symbols}

    def latest_quotes(self, symbols):
        return {symbol: {} for symbol in symbols}

    def clock(self):
        return {"timestamp": NOW.isoformat()}


class _FredProvider:
    def get_latest_value(self, series):
        return {"series": series, "date": NOW.date().isoformat(), "value": 1.0}


class _DirectClient:
    failed_symbol = ""

    def historical_bars(self, symbols, **_kwargs):
        symbol = tuple(symbols)[0]
        if symbol == self.failed_symbol:
            raise RuntimeError("temporary public provider outage")
        return {
            symbol: (
                {"t": NOW.isoformat(), "c": 100.0, "v": 1_000_000.0},
            )
        }

    def latest_quotes(self, symbols):
        symbol = tuple(symbols)[0]
        if symbol == self.failed_symbol:
            raise RuntimeError("temporary public provider outage")
        return {
            symbol: {
                "bp": 99.9,
                "ap": 100.1,
                "bs": 100.0,
                "as": 100.0,
                "t": NOW.isoformat(),
                "last": 100.0,
            }
        }


def test_one_direct_market_outage_does_not_abort_the_entire_evidence_payload(monkeypatch) -> None:
    base = load_free_paper_pilot_universe()
    direct = load_direct_global_market_universe()
    failed = direct.instruments[0].symbol
    available = direct.instruments[1].symbol
    _DirectClient.failed_symbol = failed
    universe = replace(
        base,
        identifier=f"{base.identifier}+degradation-test",
        instruments=tuple((*base.instruments, *direct.instruments[:2])),
    )

    monkeypatch.setattr(evidence, "create_alpaca_paper_client", lambda: _AlpacaClient())
    monkeypatch.setattr(evidence, "FREDProvider", _FredProvider)
    monkeypatch.setattr(evidence, "DirectGlobalMarketClient", _DirectClient)

    payload = evidence._default_probe(universe, NOW)

    assert failed not in payload["bars"]
    assert failed not in payload["quotes"]
    assert available in payload["bars"]
    assert available in payload["quotes"]
    assert failed in payload["_direct_market_errors"]
    assert "temporary public provider outage" in payload["_direct_market_errors"][failed]
