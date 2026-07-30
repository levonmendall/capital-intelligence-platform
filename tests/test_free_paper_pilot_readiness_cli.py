from __future__ import annotations

from datetime import datetime, timezone

import pytest

from run_free_paper_pilot_readiness import _evaluated_at


def test_omitted_evaluated_at_preserves_live_mode() -> None:
    assert _evaluated_at(None) is None


def test_explicit_evaluated_at_remains_point_in_time() -> None:
    assert _evaluated_at("2026-07-30T19:00:00Z") == datetime(
        2026,
        7,
        30,
        19,
        0,
        tzinfo=timezone.utc,
    )


def test_explicit_evaluated_at_requires_offset() -> None:
    with pytest.raises(ValueError, match="must include a UTC offset"):
        _evaluated_at("2026-07-30T19:00:00")
