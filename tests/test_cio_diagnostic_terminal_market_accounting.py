from api.routes.cio_diagnostic import _market_lanes


def test_complete_lane_may_be_fully_excluded_without_selected_candidate() -> None:
    lanes = _market_lanes(
        {
            "crypto": {
                "scheduled": True,
                "schedule_reason": "always_open",
                "catalog": 17,
                "deep": 0,
                "selected": 0,
            }
        },
        comprehensive_discovery_complete=True,
    )

    assert lanes == (
        {
            "asset_class": "crypto",
            "scheduled": True,
            "schedule_reason": "always_open",
            "catalog_count": 17,
            "deep_analyzed_count": 0,
            "selected_count": 0,
            "represented": True,
        },
    )


def test_empty_scheduled_catalog_remains_fail_closed() -> None:
    lanes = _market_lanes(
        {
            "fx": {
                "scheduled": True,
                "schedule_reason": "weekday",
                "catalog": 0,
                "deep": 0,
                "selected": 0,
            }
        },
        comprehensive_discovery_complete=True,
    )

    assert lanes[0]["represented"] is False


def test_incomplete_comprehensive_scope_cannot_certify_nonempty_lane() -> None:
    lanes = _market_lanes(
        {
            "future": {
                "scheduled": True,
                "schedule_reason": "weekday",
                "catalog": 13,
                "deep": 13,
                "selected": 4,
            }
        },
        comprehensive_discovery_complete=False,
    )

    assert lanes[0]["represented"] is False


def test_unscheduled_lane_is_not_required_for_current_cycle() -> None:
    lanes = _market_lanes(
        {
            "global_equity": {
                "scheduled": False,
                "schedule_reason": "weekend_market_closed",
                "catalog": 0,
                "deep": 0,
                "selected": 0,
            }
        },
        comprehensive_discovery_complete=False,
    )

    assert lanes[0]["represented"] is True
