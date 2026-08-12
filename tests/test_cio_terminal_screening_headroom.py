from operations import comprehensive_market_discovery as discovery
from operations import bounded_terminal_screening as screening


def test_production_terminal_screening_chunk_preserves_full_international_lane():
    record_count = 45_286
    records = tuple(range(record_count))

    chunks = tuple(
        chunk
        for _start, chunk in screening._chunks(
            records,
            discovery._PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE,
        )
    )

    assert discovery._PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE == 64
    assert chunks
    assert max(len(chunk) for chunk in chunks) <= 64
    assert sum(len(chunk) for chunk in chunks) == record_count
    assert tuple(item for chunk in chunks for item in chunk) == records


def test_canonical_discovery_explicitly_uses_production_screening_chunk_bound():
    import inspect

    source = inspect.getsource(discovery.discover_comprehensive_markets)

    assert "chunk_size=_PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE" in source
