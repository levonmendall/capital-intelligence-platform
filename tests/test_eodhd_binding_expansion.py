from __future__ import annotations

import json
from pathlib import Path

from run_eodhd_binding_expansion import main


class FakeSnapshot:
    content_hash = "a" * 64
    payload = {
        "active": [
            {
                "Code": "AAPL",
                "Exchange": "NASDAQ",
                "Country": "USA",
                "Currency": "USD",
                "Type": "Common Stock",
            },
            {
                "Code": "SPY",
                "Exchange": "NYSE ARCA",
                "Country": "USA",
                "Currency": "USD",
                "Type": "ETF",
            },
        ],
        "delisted": [],
    }


class FakeProvider:
    def fetch_dataset(self, query):
        assert query.provider_symbol == "US"
        return FakeSnapshot()


def test_expansion_generates_deterministic_research_bindings(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "run_eodhd_binding_expansion.build_eodhd_provider", lambda: FakeProvider()
    )
    target = tmp_path / "bindings.json"
    result = main(
        [
            "--exchange",
            "US",
            "--output",
            str(target),
            "--as-of",
            "2026-07-28T22:00:00+00:00",
        ]
    )
    assert result == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert len(payload["bindings"]) == 2
    assert payload["bindings"][0]["provider_symbol"].endswith(".US")
    assert len(payload["manifest_sha256"]) == 64
    assert any("not a survivorship-safe" in item for item in payload["limitations"])
