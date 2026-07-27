from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.market import (
    BarInterval,
    CorporateActionType,
    MarketDataQuery,
    MarketDataType,
)
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import (
    EODHDBindingRegistry,
    EODHDInstrumentBinding,
    EODHDProvider,
    EODHDProviderError,
    EODHDRetrievalPolicy,
    load_eodhd_bindings,
)
from run_eodhd_provider import main as run_eodhd_main


NOW = datetime(2026, 7, 27, 22, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def binding() -> EODHDInstrumentBinding:
    return EODHDInstrumentBinding(
        instrument_id="instrument:us-equity:aapl",
        provider_symbol="AAPL.US",
        venue="XNAS",
        currency="USD",
    )


def provider_for(payloads, *, policy=None, sleepers=None) -> EODHDProvider:
    queue = list(payloads)

    def http_get(url, *, params, timeout):
        assert params["api_token"] == "secret-token"
        assert params["fmt"] == "json"
        return queue.pop(0)

    return EODHDProvider(
        api_token="secret-token",
        bindings=EODHDBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=http_get,
        sleeper=(sleepers.append if sleepers is not None else lambda _: None),
        retrieval_policy=policy,
    )


def test_binding_registry_is_stable_and_rejects_duplicates() -> None:
    item = binding()
    registry = EODHDBindingRegistry((item,))
    assert registry.resolve(item.instrument_id) == item
    with pytest.raises(ValueError, match="duplicate EODHD instrument"):
        EODHDBindingRegistry((item, item))
    with pytest.raises(EODHDProviderError, match="no EODHD binding"):
        registry.resolve("missing")


def test_daily_bars_are_normalized_and_incomplete_current_day_is_excluded() -> None:
    provider = provider_for(
        [
            FakeResponse(
                [
                    {
                        "date": "2026-07-24",
                        "open": 210.0,
                        "high": 214.0,
                        "low": 209.0,
                        "close": 213.0,
                        "volume": 1000,
                    },
                    {
                        "date": "2026-07-27",
                        "open": 214.0,
                        "high": 216.0,
                        "low": 212.0,
                        "close": 215.0,
                        "volume": 500,
                    },
                ]
            )
        ]
    )
    batch = provider.fetch(
        MarketDataQuery(
            instrument_id=binding().instrument_id,
            data_type=MarketDataType.BAR,
            interval=BarInterval.DAY,
            as_of=NOW,
            start_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
    )
    assert len(batch.records) == 1
    record = batch.records[0]
    assert record.close == 213.0
    assert record.provenance.provider == "EODHD"
    assert record.provenance.venue == "XNAS"


def test_quote_requests_fail_closed_instead_of_using_close_as_bid_ask() -> None:
    provider = provider_for([])
    with pytest.raises(EODHDProviderError, match="does not fabricate quotes"):
        provider.fetch(
            MarketDataQuery(
                instrument_id=binding().instrument_id,
                data_type=MarketDataType.QUOTE,
                as_of=NOW,
            )
        )


def test_dividends_and_splits_normalize_without_inventing_other_actions() -> None:
    provider = provider_for(
        [
            FakeResponse(
                [
                    {
                        "date": "2026-05-15",
                        "declarationDate": "2026-04-20",
                        "value": 0.25,
                        "currency": "USD",
                    }
                ]
            ),
            FakeResponse([{"date": "2025-06-01", "split": "4/1"}]),
        ]
    )
    batch = provider.fetch(
        MarketDataQuery(
            instrument_id=binding().instrument_id,
            data_type=MarketDataType.CORPORATE_ACTION,
            as_of=NOW,
            start_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    assert [item.action_type for item in batch.records] == [
        CorporateActionType.SPLIT,
        CorporateActionType.CASH_DIVIDEND,
    ]
    assert batch.records[0].ratio == 4.0
    assert batch.records[1].amount == 0.25
    assert batch.records[1].provenance.observed_at.date().isoformat() == "2026-04-20"


def test_raw_fundamentals_snapshot_preserves_hash_and_limitations() -> None:
    provider = provider_for(
        [FakeResponse({"General": {"Code": "AAPL", "Exchange": "US"}})]
    )
    snapshot = provider.fetch_dataset(
        ProviderDatasetQuery(
            dataset_type=ProviderDatasetType.FUNDAMENTALS,
            provider_symbol="AAPL.US",
            as_of=NOW,
        )
    )
    payload = snapshot.to_dict()
    assert payload["provider"] == "EODHD"
    assert payload["dataset_type"] == "fundamentals"
    assert len(payload["content_hash"]) == 64
    assert "point-in-time statement availability" in " ".join(
        payload["limitations"]
    )
    assert "secret-token" not in json.dumps(payload)


def test_symbol_directory_remains_non_authoritative_history() -> None:
    provider = provider_for(
        [
            FakeResponse(
                [
                    {
                        "Code": "AAPL",
                        "Name": "Apple Inc",
                        "Country": "USA",
                        "Exchange": "NASDAQ",
                        "Currency": "USD",
                        "Type": "Common Stock",
                    }
                ]
            ),
            FakeResponse([]),
        ]
    )
    snapshot = provider.fetch_dataset(
        ProviderDatasetQuery(
            dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
            provider_symbol="US",
            as_of=NOW,
        )
    )
    assert snapshot.payload["active"][0]["Code"] == "AAPL"
    assert snapshot.payload["delisted"] == []
    assert any("historical identifier" in item for item in snapshot.limitations)


def test_retry_is_bounded_and_secrets_are_not_in_error() -> None:
    sleepers: list[float] = []
    provider = provider_for(
        [FakeResponse({}, 503), FakeResponse({"dailyRateLimit": 100000})],
        sleepers=sleepers,
        policy=EODHDRetrievalPolicy(max_attempts=2, backoff_seconds=0.5),
    )
    snapshot = provider.fetch_dataset(
        ProviderDatasetQuery(
            dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
            provider_symbol="ACCOUNT",
            as_of=NOW,
        )
    )
    assert snapshot.payload["dailyRateLimit"] == 100000
    assert sleepers == [0.5]


def test_missing_token_fails_closed() -> None:
    provider = EODHDProvider(
        api_token=None,
        bindings=EODHDBindingRegistry((binding(),)),
        clock=lambda: NOW,
        http_get=lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
    )
    provider.api_token = None
    with pytest.raises(EODHDProviderError, match="API_TOKEN"):
        provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
                provider_symbol="ACCOUNT",
                as_of=NOW,
            )
        )


def test_binding_file_loader(tmp_path: Path) -> None:
    path = tmp_path / "bindings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "eodhd-instrument-bindings.v1",
                "bindings": [
                    {
                        "instrument_id": binding().instrument_id,
                        "provider_symbol": "AAPL.US",
                        "venue": "XNAS",
                        "currency": "USD",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_eodhd_bindings(path)
    assert registry.resolve(binding().instrument_id).provider_symbol == "AAPL.US"


def test_cli_probe_never_prints_token(monkeypatch, capsys) -> None:
    provider = provider_for([FakeResponse({"dailyRateLimit": 100000})])
    monkeypatch.setattr("run_eodhd_provider._provider", lambda _: provider)
    assert run_eodhd_main(["probe", "--as-of", NOW.isoformat()]) == 0
    output = capsys.readouterr().out
    assert "dailyRateLimit" in output
    assert "secret-token" not in output
    assert '"secret_values_disclosed": false' in output
