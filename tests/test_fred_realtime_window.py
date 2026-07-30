from __future__ import annotations

from datetime import date

from historical_replay.sources import build_sources
from historical_replay.sources_fred import FredSource


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class PartialFredClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, _url, *, params):
        self.calls.append(dict(params))
        if params["series_id"] == "GDP":
            raise RuntimeError("one series is temporarily unavailable")
        return JsonResponse(
            {
                "observations": [
                    {
                        "date": "2020-01-01",
                        "value": "1.50",
                        "realtime_start": "2020-01-02",
                        "realtime_end": "9999-12-31",
                    }
                ]
            }
        )


class ChunkedFredClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, _url, *, params):
        payload = dict(params)
        self.calls.append(payload)
        release = str(payload["realtime_start"])
        return JsonResponse(
            {
                "observations": [
                    {
                        "date": release,
                        "value": "2.00",
                        "realtime_start": release,
                        "realtime_end": "9999-12-31",
                    }
                ]
            }
        )


class EmptyFredClient:
    def get(self, _url, *, params):
        return JsonResponse({"observations": []})


def test_fred_initial_release_collection_uses_explicit_realtime_window() -> None:
    client = PartialFredClient()
    result = FredSource(
        client,
        ("GDP", "FEDFUNDS"),
        api_key="a" * 32,
    ).collect(
        date(2020, 1, 1),
        date(2020, 1, 31),
        max_records=100,
    )

    assert result.state == "degraded"
    assert len(result.records) == 1
    assert result.records[0].dataset == "series.fedfunds"
    assert result.records[0].strict_replay_eligible is True
    assert result.records[0].available_at == "2020-01-02T00:00:00Z"
    assert "series_failed_count:1" in result.warnings
    assert "fred_initial_release_explicit_realtime_window" in result.warnings
    assert all(call["output_type"] == 4 for call in client.calls)
    assert all(call["realtime_start"] == "2019-12-01" for call in client.calls)
    assert all(call["realtime_end"] == "2020-01-31" for call in client.calls)
    assert all(call["observation_start"] == "2019-12-01" for call in client.calls)
    assert all(call["observation_end"] == "2020-01-31" for call in client.calls)


def test_fred_realtime_window_is_chunked_for_long_backfills() -> None:
    client = ChunkedFredClient()
    result = FredSource(
        client,
        ("VIXCLS",),
        api_key="a" * 32,
    ).collect(
        date(2016, 7, 30),
        date(2026, 7, 30),
        max_records=100,
    )

    assert result.state == "available"
    assert len(client.calls) > 1
    assert len(result.records) == len(client.calls)
    assert client.calls[0]["realtime_start"] == "2016-06-29"
    assert client.calls[-1]["realtime_end"] == "2026-07-30"
    for call in client.calls:
        left = date.fromisoformat(str(call["realtime_start"]))
        right = date.fromisoformat(str(call["realtime_end"]))
        assert (right - left).days <= 365


def test_empty_requested_series_fails_closed() -> None:
    result = FredSource(
        EmptyFredClient(),
        ("FEDFUNDS",),
        api_key="a" * 32,
    ).collect(
        date(2020, 1, 1),
        date(2020, 1, 31),
        max_records=100,
    )

    assert result.state == "unavailable"
    assert result.records == ()
    assert result.blockers == ("series_collection_failed_count:1",)


def test_source_factory_uses_realtime_safe_fred_adapter() -> None:
    sources = build_sources(
        {
            "sources": {
                "fred": {"enabled": True, "series": ["FEDFUNDS"]},
                "coinbase": {"enabled": False},
                "stooq": {"enabled": False},
                "world_bank": {"enabled": False},
                "federal_register": {"enabled": False},
                "sec_edgar": {"enabled": False},
                "cftc": {"enabled": False},
                "treasury_fiscal_data": {"enabled": False},
                "gdelt": {"enabled": False},
            }
        },
        user_agent="test",
    )

    assert len(sources) == 1
    assert isinstance(sources[0], FredSource)
