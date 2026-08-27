import operations.pre_comprehensive_cache_reclamation as reclamation


def _resolved_reclaim_limit(values: dict[str, str]) -> int:
    return reclamation._bounded_int(
        values,
        reclamation._RECLAIM_MAX_FILES_ENV,
        reclamation._DEFAULT_RECLAIM_MAX_FILES,
        minimum=1,
        maximum=16_384,
    )


def test_default_reclaim_budget_covers_observed_production_population() -> None:
    assert reclamation._DEFAULT_RECLAIM_MAX_FILES == 16_384
    assert _resolved_reclaim_limit({}) == 16_384
    assert _resolved_reclaim_limit({}) >= 10_831


def test_reclaim_budget_remains_hard_bounded() -> None:
    assert _resolved_reclaim_limit(
        {reclamation._RECLAIM_MAX_FILES_ENV: "999999"}
    ) == 16_384


def test_invalid_or_nonpositive_override_falls_back_to_bounded_default() -> None:
    assert _resolved_reclaim_limit(
        {reclamation._RECLAIM_MAX_FILES_ENV: "not-an-int"}
    ) == 16_384
    assert _resolved_reclaim_limit(
        {reclamation._RECLAIM_MAX_FILES_ENV: "0"}
    ) == 1
