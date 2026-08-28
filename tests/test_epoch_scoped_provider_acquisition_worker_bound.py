from __future__ import annotations

from operations import epoch_scoped_provider_acquisition as fanout


def test_render_provider_fanout_defaults_to_established_six_worker_bound() -> None:
    assert fanout._DEFAULT_WORKERS == 6
    assert fanout._MAX_WORKERS == 6
    assert fanout._worker_count({"RENDER": "true"}) == 6


def test_provider_fanout_worker_override_remains_bounded() -> None:
    values = {
        "RENDER": "true",
        fanout._WORKERS_ENV: "99",
    }

    assert fanout._worker_count(values) == 6


def test_provider_fanout_can_still_be_reduced_operationally() -> None:
    values = {
        "RENDER": "true",
        fanout._WORKERS_ENV: "3",
    }

    assert fanout._worker_count(values) == 3
