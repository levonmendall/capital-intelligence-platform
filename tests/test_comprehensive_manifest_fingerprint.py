from __future__ import annotations

import gc
import weakref
from datetime import datetime, timezone

from operations import comprehensive_market_discovery as discovery


AS_OF = datetime(2026, 8, 7, 23, 45, tzinfo=timezone.utc)
POLICY = "comprehensive-liquid-market-discovery.v6-provider-publication-authority"


class _TrackedLane(dict):
    pass


def _lane(asset_class: str, count: int) -> _TrackedLane:
    return _TrackedLane(
        {
            "asset_class": asset_class,
            "scheduled": True,
            "catalog": count,
            "preselection": {
                "selected_symbols": [f"SYMBOL_{index}" for index in range(count)],
                "scores": {
                    f"SYMBOL_{index}": {"quality": index / max(1, count)}
                    for index in range(count)
                },
            },
            "sources": [f"provider:record:{index}" for index in range(count)],
        }
    )


def test_streaming_manifest_matches_legacy_compact_sorted_json_hash() -> None:
    lanes = (
        _lane("international_equity", 7),
        _lane("option", 3),
        _TrackedLane(
            {
                "asset_class": "future",
                "scheduled": False,
                "schedule_reason": "weekend_market_closed",
                "catalog": 0,
                "selected": [],
                "unicode_evidence": "crédit",
            }
        ),
    )
    streaming = discovery._StreamingManifestFingerprint(
        as_of=AS_OF,
        policy=POLICY,
    )
    for lane in lanes:
        streaming.append(lane)

    expected = discovery._base._legacy._hash(
        {
            "as_of": AS_OF.isoformat(),
            "policy": POLICY,
            "candidate_count_limit_applied": False,
            "lanes": list(lanes),
        }
    )

    assert streaming.hexdigest() == expected
    assert streaming.hexdigest() == expected


def test_streaming_manifest_does_not_retain_completed_lane_material() -> None:
    streaming = discovery._StreamingManifestFingerprint(
        as_of=AS_OF,
        policy=POLICY,
    )
    lane = _lane("international_equity", 2_000)
    lane_reference = weakref.ref(lane)

    streaming.append(lane)
    del lane
    gc.collect()

    assert lane_reference() is None
    assert len(streaming.hexdigest()) == 64
