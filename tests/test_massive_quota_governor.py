from __future__ import annotations

import json

from providers.massive_quota_governor import reserve_massive_request


def test_massive_requests_share_one_persistent_interval(tmp_path) -> None:
    sleeps: list[float] = []
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MASSIVE_GLOBAL_MIN_INTERVAL_SECONDS": "12.5",
    }

    first = reserve_massive_request(values=values, sleeper=sleeps.append, now=lambda: 100.0)
    second = reserve_massive_request(values=values, sleeper=sleeps.append, now=lambda: 100.0)
    third = reserve_massive_request(values=values, sleeper=sleeps.append, now=lambda: 100.0)

    assert first == 0.0
    assert second == 12.5
    assert third == 25.0
    assert sleeps == [12.5, 25.0]
    payload = json.loads(
        (tmp_path / "provider_limits" / "massive-global-rate.json").read_text(encoding="utf-8")
    )
    assert payload["last_reserved_epoch"] == 125.0
    assert payload["minimum_interval_seconds"] == 12.5


def test_massive_governor_can_be_explicitly_disabled(tmp_path) -> None:
    sleeps: list[float] = []
    delay = reserve_massive_request(
        values={
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_MASSIVE_GLOBAL_MIN_INTERVAL_SECONDS": "0",
        },
        sleeper=sleeps.append,
        now=lambda: 100.0,
    )

    assert delay == 0.0
    assert sleeps == []
