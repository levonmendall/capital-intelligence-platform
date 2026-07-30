from __future__ import annotations

from datetime import date
from pathlib import Path

from historical_replay import runtime


class _BackfillResult:
    def as_dict(self) -> dict[str, object]:
        return {"state": "available", "records_written": 10}


class _Coordinator:
    def run(self, **_: object) -> _BackfillResult:
        return _BackfillResult()


def _install_fakes(
    monkeypatch,
    tmp_path: Path,
    *,
    report: dict[str, object],
) -> dict[str, object]:
    root = tmp_path / "historical_replay"
    captured: dict[str, object] = {}

    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR", str(root))
    monkeypatch.setattr(
        runtime,
        "ten_year_window",
        lambda: (date(2016, 1, 1), date(2026, 1, 1)),
    )
    monkeypatch.setattr(
        runtime,
        "coordinator_from_config",
        lambda **_: _Coordinator(),
    )
    monkeypatch.setattr(runtime, "HistoricalStore", lambda path: path)
    monkeypatch.setattr(
        runtime,
        "HistoricalCanonicalContextBuilder",
        lambda **values: values,
    )

    class _Engine:
        def __init__(self, store, *, builder) -> None:
            captured["store"] = store
            captured["builder"] = builder

        def run(self, **values: object) -> dict[str, object]:
            captured["run"] = values
            return dict(report)

    monkeypatch.setattr(
        runtime,
        "MacroCompleteCanonicalHistoricalReplayEngine",
        _Engine,
    )
    captured["root"] = root
    return captured


def _report(*, certification_ready: bool) -> dict[str, object]:
    return {
        "runtime_version": "single-pass-availability-cursor.v5",
        "archive_scan_count": 1,
        "relevant_record_count": 16_946,
        "canonical_cio_invoked_count": 117,
        "blocked_cutoff_count": 3,
        "decision_cutoff_count": 120,
        "ending_portfolio_value": 250_000.0,
        "strict_replay": True,
        "macro_coverage_satisfied": certification_ready,
        "certification_ready": certification_ready,
        "calibration_eligible_observation_count": 190,
    }


def test_persistent_runtime_uses_macro_complete_learning_engine(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured = _install_fakes(
        monkeypatch,
        tmp_path,
        report=_report(certification_ready=True),
    )

    payload = runtime.run_once()

    replay = payload["canonical_replay"]
    assert isinstance(replay, dict)
    assert replay["state"] == "available"
    assert replay["runtime_version"] == "single-pass-availability-cursor.v5"
    assert replay["macro_coverage_satisfied"] is True
    assert replay["certification_ready"] is True
    assert replay["calibration_eligible_observation_count"] == 190
    assert replay["learning_manifest"] == str(
        captured["root"] / "manifests" / "latest-canonical-learning.json"
    )
    assert captured["store"] == captured["root"]


def test_persistent_runtime_stays_blocked_until_learning_is_certified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_fakes(
        monkeypatch,
        tmp_path,
        report=_report(certification_ready=False),
    )

    payload = runtime.run_once()

    replay = payload["canonical_replay"]
    assert isinstance(replay, dict)
    assert replay["canonical_cio_invoked_count"] == 117
    assert replay["state"] == "blocked"
    assert replay["macro_coverage_satisfied"] is False
    assert replay["certification_ready"] is False
