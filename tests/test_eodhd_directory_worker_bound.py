from operations._comprehensive_market_discovery_v4 import _MAX_DIRECTORY_IO_WORKERS


def test_eodhd_directory_worker_bound_is_fixed():
    assert _MAX_DIRECTORY_IO_WORKERS == 4
