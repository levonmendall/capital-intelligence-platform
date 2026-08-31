from __future__ import annotations

from typing import Any

import operations.current_asset_class_evaluation_status as current


_RELEASE = "release-current"
_EPOCH = "2026-08-31T03:31:00+00:00"


def _dag_rows() -> list[dict[str, object]]:
    return [
        {
            "key": lane,
            "asset_class": current.validated._label(lane),
            "status": "In progress",
            "detail": "Scheduled for the current comprehensive evaluation",
        }
        for lane in current.validated._GOVERNED_ASSET_CLASSES
    ]


def _terminal_subset(count: int = 2) -> dict[str, object]:
    rows = [
        {
            "key": lane,
            "asset_class": current.validated._label(lane),
            "status": "Evaluated",
            "detail": "10 cataloged · 10 deep analyzed · 1 selected",
        }
        for lane in current.validated._GOVERNED_ASSET_CLASSES[:count]
    ]
    return current.validated._summary(
        rows,
        as_of=_EPOCH,
        source="Current all-market evaluation",
    )


def _install_attempt(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        current.validated,
        "_latest_dag_attempt",
        lambda _values: {
            "release_sha": _RELEASE,
            "decision_epoch": _EPOCH,
            "rows": _dag_rows(),
        },
    )


def test_partial_terminal_aggregate_enriches_dag_without_erasing_active_lanes(monkeypatch):
    _install_attempt(monkeypatch)
    monkeypatch.setattr(current, "load_public_lane_telemetry", lambda _values: None)
    monkeypatch.setattr(
        current.validated,
        "_terminal_evaluation_attempt",
        lambda *_args, **_kwargs: _terminal_subset(2),
    )

    result = current.load_current_asset_class_evaluation_status(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE}
    )

    assert result["source"] == "Current all-market evaluation"
    assert result["release_sha"] == _RELEASE
    assert result["decision_epoch"] == _EPOCH
    assert result["exact_release"] is True
    assert result["historical"] is False
    assert result["reached"] == result["total"] == 13
    assert result["successful"] == 2
    assert sum(row["status"] == "Evaluated" for row in result["rows"]) == 2
    assert sum(row["status"] == "In progress" for row in result["rows"]) == 11
    assert sum(row["status"] == "Awaiting evaluation" for row in result["rows"]) == 0


def test_exact_lane_telemetry_refines_nonterminal_phase_but_terminal_result_wins(monkeypatch):
    _install_attempt(monkeypatch)
    first, second = current.validated._GOVERNED_ASSET_CLASSES[:2]
    monkeypatch.setattr(
        current,
        "load_public_lane_telemetry",
        lambda _values: {
            "release": _RELEASE,
            "decision_epoch": _EPOCH,
            "lanes": [
                {
                    "asset_class": first,
                    "screening_started_at": "2026-08-31T03:32:00+00:00",
                    "screening_completed_at": None,
                    "lane_failed_at": None,
                    "lane_completed_at": None,
                },
                {
                    "asset_class": second,
                    "publication_started_at": "2026-08-31T03:32:00+00:00",
                    "publication_completed_at": None,
                    "lane_failed_at": None,
                    "lane_completed_at": None,
                },
            ],
        },
    )
    terminal = current.validated._summary(
        [
            {
                "key": first,
                "asset_class": current.validated._label(first),
                "status": "Evaluated",
                "detail": "10 cataloged · 10 deep analyzed · 1 selected",
            }
        ],
        as_of=_EPOCH,
        source="Current all-market evaluation",
    )
    monkeypatch.setattr(
        current.validated,
        "_terminal_evaluation_attempt",
        lambda *_args, **_kwargs: terminal,
    )

    result = current.load_current_asset_class_evaluation_status(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE}
    )
    by_lane = {row["key"]: row for row in result["rows"]}

    assert by_lane[first]["status"] == "Evaluated"
    assert "cataloged" in by_lane[first]["detail"]
    assert by_lane[second]["status"] == "In progress"
    assert by_lane[second]["detail"] == "Provider publication in progress"


def test_cross_epoch_telemetry_cannot_relabel_current_dag(monkeypatch):
    _install_attempt(monkeypatch)
    first = current.validated._GOVERNED_ASSET_CLASSES[0]
    monkeypatch.setattr(
        current,
        "load_public_lane_telemetry",
        lambda _values: {
            "release": _RELEASE,
            "decision_epoch": "2026-08-31T02:00:00+00:00",
            "lanes": [
                {
                    "asset_class": first,
                    "lane_failed_at": "2026-08-31T02:05:00+00:00",
                    "error_type": "StaleFailure",
                }
            ],
        },
    )
    monkeypatch.setattr(
        current.validated,
        "_terminal_evaluation_attempt",
        lambda *_args, **_kwargs: None,
    )

    result = current.load_current_asset_class_evaluation_status(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE}
    )
    by_lane = {row["key"]: row for row in result["rows"]}

    assert by_lane[first]["status"] == "In progress"
    assert "StaleFailure" not in by_lane[first]["detail"]


def test_historical_completed_evaluation_is_explicitly_marked_historical(monkeypatch):
    monkeypatch.setattr(current.validated, "_latest_dag_attempt", lambda _values: None)
    monkeypatch.setattr(current, "load_public_lane_telemetry", lambda _values: None)
    monkeypatch.setattr(current.validated, "_release", lambda _values: _RELEASE)
    monkeypatch.setattr(
        current.validated,
        "_terminal_evaluation_attempt",
        lambda *_args, **_kwargs: None,
    )
    historical = current.validated._summary(
        [
            {
                "key": current.validated._GOVERNED_ASSET_CLASSES[0],
                "asset_class": "U.S. equities",
                "status": "Evaluated",
                "detail": "historical",
            }
        ],
        as_of="2026-08-30T20:00:00+00:00",
        source="Latest completed global evaluation",
    )
    monkeypatch.setattr(
        current.validated,
        "_latest_completed_snapshot",
        lambda _values: historical,
    )

    result = current.load_current_asset_class_evaluation_status(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE}
    )
    previous = current.load_latest_completed_asset_class_evaluation(
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE}
    )

    assert result["historical"] is True
    assert result["exact_release"] is False
    assert result["source"] == "Latest completed global evaluation"
    assert previous is not None
    assert previous["historical"] is True
