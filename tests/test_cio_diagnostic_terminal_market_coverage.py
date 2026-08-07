from __future__ import annotations

from api.routes.cio_diagnostic import _market_lanes


def _payload() -> dict[str, dict[str, object]]:
    return {
        "crypto": {
            "scheduled": True,
            "catalog": 8,
            "deep": 0,
            "selected": 0,
            "terminal_selected_count": 0,
            "terminal_excluded_count": 8,
            "terminal_accounting_complete": True,
        },
        "fx": {
            "scheduled": True,
            "catalog": 0,
            "deep": 0,
            "selected": 0,
        },
        "option": {
            "scheduled": False,
            "schedule_reason": "weekend_market_closed",
            "catalog": 0,
            "deep": 0,
            "selected": 0,
        },
    }


def test_release_audit_accepts_terminally_accounted_zero_candidate_lane() -> None:
    lanes = _market_lanes(
        _payload(),
        comprehensive_discovery_complete=True,
    )

    by_asset_class = {str(item["asset_class"]): item for item in lanes}
    assert by_asset_class["crypto"]["represented"] is True
    assert by_asset_class["crypto"]["selected_count"] == 0
    assert by_asset_class["fx"]["represented"] is False
    assert by_asset_class["option"]["represented"] is True


def test_release_audit_keeps_scheduled_lane_fail_closed_before_scope_completion() -> None:
    lanes = _market_lanes(
        _payload(),
        comprehensive_discovery_complete=False,
    )

    by_asset_class = {str(item["asset_class"]): item for item in lanes}
    assert by_asset_class["crypto"]["represented"] is False
    assert by_asset_class["fx"]["represented"] is False
    assert by_asset_class["option"]["represented"] is True
