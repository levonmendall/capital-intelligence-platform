from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cio.governed_historical_learning as governed
import cio.historical_learning as historical
from cio.models import CandidateAssetClass, CandidateDecisionRecord, CandidateInstrument
from operations import bounded_historical_learning as bounded
from operations import bounded_governed_historical_learning as bounded_governed

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


def _decision(
    symbol: str,
    *,
    stage: str,
    confidence: float,
    weight: float,
    realized: float,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "asset_class": "crypto" if symbol == "BTC-USD" else "us_equity",
        "decision_stage": stage,
        "decision_horizon_days": 30,
        "macro_regime": "expansion",
        "market_regime": "risk_on",
        "action": "buy",
        "final_confidence": confidence,
        "recommended_position_weight": weight,
        "realized_return_to_next_cutoff": realized,
    }


def _learning_manifest(path: Path) -> None:
    payload = {
        "schema_version": "canonical-historical-learning-input.v1",
        "generated_at": "2026-08-18T12:00:00+00:00",
        "strict_only": True,
        "outcome_alignment": "decision_horizon",
        "macro_coverage_satisfied": True,
        "required_macro_datasets": ["policy_rate", "yield_curve", "volatility"],
        "certification_ready": True,
        "governance_only_observation_count": 2,
        "bounded_calibration_outcome_count": 1,
        "macro_excluded_observation_count": 3,
        "qualification_observation_count": 3,
        "cio_decision_observation_count": 3,
        "decisions": [
            {
                "state": "completed",
                "macro_regime": "expansion",
                "decisions": [
                    _decision(
                        "AAPL",
                        stage="qualification",
                        confidence=0.68,
                        weight=0.06,
                        realized=0.03,
                    ),
                    _decision(
                        "AAPL",
                        stage="cio_synthesis",
                        confidence=0.72,
                        weight=0.07,
                        realized=0.05,
                    ),
                    _decision(
                        "MSFT",
                        stage="cio_synthesis",
                        confidence=0.64,
                        weight=0.05,
                        realized=0.01,
                    ),
                    _decision(
                        "BTC-USD",
                        stage="cio_synthesis",
                        confidence=0.91,
                        weight=0.20,
                        realized=0.40,
                    ),
                ],
            },
            {
                "state": "completed",
                "macro_regime": "expansion",
                "decisions": [
                    _decision(
                        "AAPL",
                        stage="cio_synthesis",
                        confidence=0.60,
                        weight=0.04,
                        realized=-0.02,
                    ),
                    _decision(
                        "MSFT",
                        stage="qualification",
                        confidence=0.61,
                        weight=0.04,
                        realized=0.00,
                    ),
                ],
            },
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_bounded_governed_resolver_matches_canonical_semantics(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "latest-canonical-learning.json"
    _learning_manifest(path)
    candidate = _candidate()
    as_of = datetime(2026, 8, 19, 12, tzinfo=UTC)

    resolver = governed.HistoricalLearningResolver(path, minimum_sample_size=2)
    prior_base_resolve = historical.HistoricalLearningResolver.resolve
    monkeypatch.setattr(
        historical.HistoricalLearningResolver,
        "resolve",
        bounded._ORIGINAL_RESOLVE,
    )
    expected = bounded_governed._ORIGINAL_GOVERNED_RESOLVE(
        resolver,
        candidate,
        as_of=as_of,
        macro_regime="expansion",
        market_regime="risk_on",
    )
    monkeypatch.setattr(
        historical.HistoricalLearningResolver,
        "resolve",
        prior_base_resolve,
    )

    bounded_governed.install_bounded_governed_historical_learning()
    actual = governed.HistoricalLearningResolver(path, minimum_sample_size=2).resolve(
        candidate,
        as_of=as_of,
        macro_regime="expansion",
        market_regime="risk_on",
    )

    assert actual.as_dict() == expected.as_dict()
    assert actual.execution_authorized is False
    assert actual.policy_promotion_authorized is False
    assert actual.may_increase_position_size is False


def test_compact_learning_manifest_keeps_governance_metadata_and_discards_unrelated_classes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "latest-canonical-learning.json"
    _learning_manifest(path)

    compact, _signature = bounded_governed._compact_learning_manifest(
        path,
        candidate=_candidate(),
    )
    symbols = {
        item["symbol"]
        for cutoff in compact["decisions"]
        for item in cutoff["decisions"]
    }

    assert symbols == {"AAPL", "MSFT"}
    assert "BTC-USD" not in symbols
    assert compact["schema_version"] == "canonical-historical-learning-input.v1"
    assert compact["outcome_alignment"] == "decision_horizon"
    assert compact["macro_coverage_satisfied"] is True
    assert compact["certification_ready"] is True
    assert compact["cio_decision_observation_count"] == 3
    assert compact["qualification_observation_count"] == 3


def test_repeated_governed_resolution_reuses_final_compact_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "latest-canonical-learning.json"
    _learning_manifest(path)
    candidate = _candidate()
    as_of = datetime(2026, 8, 19, 12, tzinfo=UTC)
    calls = 0
    original_compact = bounded_governed._compact_learning_manifest

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_compact(*args, **kwargs)

    monkeypatch.setattr(bounded_governed, "_compact_learning_manifest", counted)
    bounded_governed.install_bounded_governed_historical_learning()
    resolver = governed.HistoricalLearningResolver(path, minimum_sample_size=2)

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
