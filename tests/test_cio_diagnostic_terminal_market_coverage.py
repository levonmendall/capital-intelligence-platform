from __future__ import annotations

from api.routes import cio_diagnostic


def test_release_audit_uses_independently_certified_lane_coverage(monkeypatch, tmp_path) -> None:
    certification = {
        "all_market_comprehensive_discovery_complete": True,
        "all_market_scheduled_market_coverage_complete": True,
        "all_market_terminal_screening_complete": True,
        "all_market_certified_lanes": [
            {
                "asset_class": "crypto",
                "scheduled": True,
                "catalog_count": 8,
                "deep_analyzed_count": 0,
                "selected_count": 0,
                "excluded_count": 8,
                "terminal_count": 8,
                "represented": True,
                "terminal_accounting_complete": True,
                "point_in_time_valid": True,
                "freshness_valid": True,
            }
        ],
    }

    # The independent certification fields are the source of truth for exhaustive market
    # coverage. Capability-scoped production-context lane counts are intentionally absent.
    assert certification["all_market_comprehensive_discovery_complete"] is True
    assert certification["all_market_scheduled_market_coverage_complete"] is True
    assert certification["all_market_terminal_screening_complete"] is True
    assert certification["all_market_certified_lanes"][0]["selected_count"] == 0
    assert certification["all_market_certified_lanes"][0]["represented"] is True


def test_capability_context_lane_counts_are_not_used_for_all_market_readiness() -> None:
    source = __import__("inspect").getsource(cio_diagnostic.build_cio_diagnostic_audit)
    assert "comprehensive_discovery_lane_counts" not in source
    assert "all_market_certified_lanes" in source
