from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cio.historical_learning as historical
from cio.models import CandidateAssetClass, CandidateDecisionRecord, CandidateInstrument
from operations import bounded_historical_learning as bounded

UTC = timezone.utc


def _candidate(symbol: str = "AAPL") -> CandidateDecisionRecord:
    instrument = object.__new__(CandidateInstrument)
    object.__setattr__(instrument, "symbol", symbol)
    object.__setattr__(instrument, "asset_class", CandidateAssetClass.US_EQUITY)
    candidate = object.__new__(CandidateDecisionRecord)
    object.__setattr__(candidate, "identifier", f"candidate:{symbol}")
    object.__setattr__(candidate, "instrument", instrument)
    object.__setattr__(candidate, "decision_horizon_days", 30)
    return candidate


def _manifest(path: Path) -> None:
    payload = {
        "generated_at": "2026-08-18T12:00:00+00:00",
        "strict_only": True,
        "decisions": [
            {
                "state": "completed",
                "macro_regime": "expansion",
                "decisions": [
                    {
                        "candidate_identifier": "history:AAPL",
                        "decision_horizon_days": 30,
                        "market_regime": "risk_on",
                        "action": "buy",
                        "final_confidence": 0.72,
                        "recommended_position_weight": 0.08,
                        "realized_return_to_next_cutoff": 0.04,
                    },
                    {
                        "symbol": "MSFT",
                        "asset_class": "us_equity",
                        "decision_horizon_days": 25,
                        "macro_regime": "expansion",
                        "market_regime": "risk_on",
                        "action": "hold",
                        "final_confidence": 0.64,
                        "recommended_position_weight": 0.06,
                        "realized_return_to_next_cutoff": 0.01,
                    },
                    {
                        "symbol": "BTC-USD",
                        "asset_class": "crypto",
                        "decision_horizon_days": 30,
                        "macro_regime": "expansion",
                        "market_regime": "risk_on",
                        "action": "buy",
                        "final_confidence": 0.90,
                        "recommended_position_weight": 0.20,
                        "realized_return_to_next_cutoff": 0.30,
                    },
                ],
            },
            {
                "state": "completed",
                "macro_regime": "expansion",
                "decisions": [
                    {
                        "symbol": "AAPL",
                        "asset_class": "us_equity",
                        "decision_horizon_days": 45,
                        "macro_regime": "expansion",
                        "market_regime": "risk_on",
                        "action": "watch",
                        "final_confidence": 0.58,
                        "recommended_position_weight": 0.04,
                        "realized_return_to_next_cutoff": -0.02,
                    }
                ],
            },
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_bounded_resolver_is_semantically_equivalent_to_canonical_resolver(tmp_path: Path) -> None:
    path = tmp_path / "latest-canonical-replay.json"
    _manifest(path)
    candidate = _candidate()
    as_of = datetime(2026, 8, 19, 12, tzinfo=UTC)

    canonical = historical.HistoricalLearningResolver(path, minimum_sample_size=2)
    expected = bounded._ORIGINAL_RESOLVE(
        canonical,
        candidate,
        as_of=as_of,
        macro_regime="expansion",
        market_regime="risk_on",
    )

    bounded.install_bounded_historical_learning()
    actual = historical.HistoricalLearningResolver(path, minimum_sample_size=2).resolve(
        candidate,
        as_of=as_of,
        macro_regime="expansion",
        market_regime="risk_on",
    )

    assert actual.as_dict() == expected.as_dict()
    assert actual.execution_authorized is False
    assert actual.policy_promotion_authorized is False
    assert actual.may_increase_position_size is False


def test_bounded_manifest_discards_unrelated_asset_classes(tmp_path: Path) -> None:
    path = tmp_path / "latest-canonical-replay.json"
    _manifest(path)

    compact, _signature = bounded._compact_manifest(path, candidate=_candidate())
    symbols = {
        item["symbol"]
        for cutoff in compact["decisions"]
        for item in cutoff["decisions"]
    }

    assert symbols == {"AAPL", "MSFT"}
    assert "BTC-USD" not in symbols
    assert set(compact) == {"generated_at", "strict_only", "decisions"}


def test_repeated_resolution_reuses_compact_context(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "latest-canonical-replay.json"
    _manifest(path)
    candidate = _candidate()
    as_of = datetime(2026, 8, 19, 12, tzinfo=UTC)
    calls = 0
    original_compact = bounded._compact_manifest

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_compact(*args, **kwargs)

    monkeypatch.setattr(bounded, "_compact_manifest", counted)
    bounded.install_bounded_historical_learning()
    resolver = historical.HistoricalLearningResolver(path, minimum_sample_size=2)

    first = resolver.resolve(
        candidate,
        as_of=as_of,
        macro_regime="expansion",
        market_regime="risk_on",
    )
    second = resolver.resolve(
        candidate,
        as_of=as_of,
        macro_regime="expansion",
        market_regime="risk_on",
    )

    assert calls == 1
    assert second is first

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    third = resolver.resolve(
        candidate,
        as_of=as_of + timedelta(seconds=1),
        macro_regime="expansion",
        market_regime="risk_on",
    )
    assert calls == 2
    assert third.as_dict()["candidate_identifier"] == candidate.identifier
