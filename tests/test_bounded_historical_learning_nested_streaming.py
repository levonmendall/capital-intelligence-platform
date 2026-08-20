from __future__ import annotations

import json
from pathlib import Path

import pytest

from cio.models import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
)
from operations import bounded_historical_learning as bounded


def _candidate(symbol: str = "AAPL") -> CandidateDecisionRecord:
    instrument = object.__new__(CandidateInstrument)
    object.__setattr__(instrument, "symbol", symbol)
    object.__setattr__(
        instrument,
        "asset_class",
        CandidateAssetClass.US_EQUITY,
    )
    candidate = object.__new__(CandidateDecisionRecord)
    object.__setattr__(candidate, "identifier", f"candidate:{symbol}")
    object.__setattr__(candidate, "instrument", instrument)
    object.__setattr__(candidate, "decision_horizon_days", 30)
    return candidate


def _decision(symbol: str, *, extra: object | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": symbol,
        "asset_class": "us_equity" if symbol != "BTC-USD" else "crypto",
        "decision_stage": "cio_synthesis",
        "decision_horizon_days": 30,
        "macro_regime": "expansion",
        "market_regime": "risk_on",
        "action": "buy",
        "final_confidence": 0.72,
        "recommended_position_weight": 0.07,
        "realized_return_to_next_cutoff": 0.05,
    }
    if extra is not None:
        payload["provider_payload"] = extra
    return payload


def test_nested_cutoffs_never_use_container_value_decode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "latest-canonical-learning.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-18T12:00:00+00:00",
                "strict_only": True,
                "ignored_top_level": {
                    "records": [{"payload": ["unused", {"deep": True}]}]
                },
                "decisions": [
                    {
                        "state": "completed",
                        "macro_regime": "expansion",
                        "ignored_cutoff": {
                            "provider_records": [
                                {"raw": [1, 2, 3]},
                                {"raw": [4, 5, 6]},
                            ]
                        },
                        "decisions": [
                            _decision(
                                "AAPL",
                                extra={
                                    "rows": [
                                        {"value": index}
                                        for index in range(20)
                                    ]
                                },
                            ),
                            _decision(
                                "BTC-USD",
                                extra={
                                    "rows": [
                                        {"value": index}
                                        for index in range(20)
                                    ]
                                },
                            ),
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    original_value = bounded._IncrementalJSONReader.value

    def scalar_only_value(self):
        token = self.peek()
        if token in {"{", "["}:
            raise AssertionError(
                "bounded historical learning attempted to materialize a JSON container"
            )
        return original_value(self)

    monkeypatch.setattr(
        bounded._IncrementalJSONReader,
        "value",
        scalar_only_value,
    )

    compact, _signature = bounded._compact_manifest(
        path,
        candidate=_candidate(),
    )

    assert compact["generated_at"] == "2026-08-18T12:00:00+00:00"
    assert compact["strict_only"] is True
    assert "ignored_top_level" not in compact
    assert len(compact["decisions"]) == 1
    decisions = compact["decisions"][0]["decisions"]
    assert [item["symbol"] for item in decisions] == ["AAPL"]
    assert "provider_payload" not in decisions[0]


def test_large_irrelevant_nested_payload_is_streamed_below_scalar_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bounded, "_CHUNK_CHARS", 256)
    monkeypatch.setattr(bounded, "_MAX_SINGLE_VALUE_CHARS", 1024)
    path = tmp_path / "latest-canonical-learning.json"
    large_blob = "x" * 16_384
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-18T12:00:00+00:00",
                "strict_only": True,
                "archive": {"blob": large_blob},
                "decisions": [
                    {
                        "state": "completed",
                        "macro_regime": "expansion",
                        "raw_cutoff_payload": {
                            "blob": large_blob,
                            "nested": [{"blob": large_blob}],
                        },
                        "decisions": [
                            _decision(
                                "AAPL",
                                extra={
                                    "blob": large_blob,
                                    "nested": [{"blob": large_blob}],
                                },
                            )
                        ],
                    }
                ],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    compact, _signature = bounded._compact_manifest(
        path,
        candidate=_candidate(),
    )

    decision = compact["decisions"][0]["decisions"][0]
    assert decision["symbol"] == "AAPL"
    assert decision["asset_class"] == "us_equity"
    assert "provider_payload" not in decision
    assert "raw_cutoff_payload" not in compact["decisions"][0]


def test_skipped_nested_payload_remains_fail_closed_on_invalid_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "latest-canonical-learning.json"
    path.write_text(
        (
            '{"generated_at":"2026-08-18T12:00:00+00:00",'
            '"ignored":{"records":[1,]},'
            '"decisions":[]}'
        ),
        encoding="utf-8",
    )

    with pytest.raises(json.JSONDecodeError):
        bounded._compact_manifest(path, candidate=_candidate())
