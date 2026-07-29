from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.market import BarInterval, MarketDataQuery, MarketDataType
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.databento import (
    DatabentoBindingRegistry,
    DatabentoInstrumentBinding,
    DatabentoProvider,
    DatabentoProviderError,
    load_databento_bindings,
)


NOW = datetime(2026, 7, 28, 22, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, *, payload=None, lines=None, status_code: int = 200):
        self._payload = payload
        self._lines = list(lines or [])
        self.status_code = status_code

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


def binding() -> DatabentoInstrumentBinding:
    return DatabentoInstrumentBinding(
        instrument_id="instrument:us-equity:aapl",
        dataset="DBEQ.BASIC",
        provider_symbol="AAPL",
        venue="DBEQ",
        currency="USD",
    )


def test_minute_bar_is_normalized_from_json_lines() -> None:
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            lines=[
                json.dumps(
                    {
                        "hd": {"ts_event": "2026-07-28T21:59:00Z", "instrument_id": 1},
                        "open": "210.0",
                        "high": "211.0",
                        "low": "209.5",
                        "close": "210.5",
                        "volume": "1000",
                        "symbol": "AAPL",
                    }
                )
            ]
        )

    provider = DatabentoProvider(
        api_key="db-test",
        bindings=DatabentoBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_post=post,
    )
    batch = provider.fetch(
        MarketDataQuery(
            instrument_id=binding().instrument_id,
            data_type=MarketDataType.BAR,
            interval=BarInterval.MINUTE,
            start_at=NOW - timedelta(minutes=1),
            as_of=NOW,
        )
    )
    assert len(batch.records) == 1
    assert batch.records[0].close == 210.5
    assert batch.records[0].provenance.provider == "DATABENTO"
    assert calls[0][1]["auth"] == ("db-test", "")
    assert calls[0][1]["data"]["encoding"] == "json"
    assert calls[0][1]["data"]["map_symbols"] == "true"


def test_quote_normalization_uses_first_mbp_level() -> None:
    provider = DatabentoProvider(
        api_key="db-test",
        bindings=DatabentoBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_post=lambda *_args, **_kwargs: FakeResponse(
            lines=[
                json.dumps(
                    {
                        "hd": {"ts_event": "2026-07-28T21:59:59Z", "instrument_id": 1},
                        "levels": [
                            {
                                "bid_px": "210.10",
                                "ask_px": "210.12",
                                "bid_sz": "200",
                                "ask_sz": "150",
                            }
                        ],
                    }
                )
            ]
        ),
    )
    record = provider.fetch(
        MarketDataQuery(
            instrument_id=binding().instrument_id,
            data_type=MarketDataType.QUOTE,
            start_at=NOW - timedelta(minutes=1),
            as_of=NOW,
        )
    ).records[0]
    assert record.bid == 210.10
    assert record.ask == 210.12
    assert record.bid_size == 200.0


def test_capability_report_is_credential_safe() -> None:
    responses = [
        FakeResponse(payload=["DBEQ.BASIC", "GLBX.MDP3"]),
        FakeResponse(payload=["trades", "mbp-1", "ohlcv-1m"]),
    ]

    def get(_url, **_kwargs):
        return responses.pop(0)

    provider = DatabentoProvider(
        api_key="db-secret",
        bindings=DatabentoBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=get,
    )
    report = provider.capability_report()
    assert report["dataset_count"] == 2
    assert report["bindings"][0]["state"] == "available"
    assert "db-secret" not in json.dumps(report)
    assert report["real_money_authorized"] is False


def test_raw_entitlement_snapshot_preserves_governance_boundary() -> None:
    provider = DatabentoProvider(
        api_key="db-test",
        bindings=DatabentoBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=lambda *_args, **_kwargs: FakeResponse(payload=["DBEQ.BASIC"]),
    )
    snapshot = provider.fetch_dataset(
        ProviderDatasetQuery(
            dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
            provider_symbol="ACCOUNT",
            as_of=NOW,
        )
    )
    assert snapshot.payload == ["DBEQ.BASIC"]
    assert any("not legal usage approval" in item for item in snapshot.limitations)
    assert len(snapshot.content_hash) == 64


def test_missing_key_fails_before_http() -> None:
    provider = DatabentoProvider(
        api_key=None,
        bindings=DatabentoBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=lambda *_args, **_kwargs: pytest.fail("HTTP must not be called"),
    )
    provider.api_key = None
    with pytest.raises(DatabentoProviderError, match="API_KEY"):
        provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
                provider_symbol="ACCOUNT",
                as_of=NOW,
            )
        )


def test_binding_loader(tmp_path: Path) -> None:
    path = tmp_path / "databento.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "databento-instrument-bindings.v1",
                "bindings": [
                    {
                        "instrument_id": binding().instrument_id,
                        "dataset": "DBEQ.BASIC",
                        "provider_symbol": "AAPL",
                        "venue": "DBEQ",
                        "currency": "USD",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_databento_bindings(path)
    assert registry.resolve(binding().instrument_id).dataset == "DBEQ.BASIC"
