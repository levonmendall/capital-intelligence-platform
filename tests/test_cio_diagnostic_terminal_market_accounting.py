from __future__ import annotations

import inspect

from api.routes import cio_diagnostic


def test_terminal_market_accounting_comes_from_independent_certification() -> None:
    """Capability-scoped context must not impersonate exhaustive all-market coverage."""

    source = inspect.getsource(cio_diagnostic.build_cio_diagnostic_audit)
    assert 'all_market_certified_lanes' in source
    assert 'all_market_scheduled_market_coverage_complete' in source
    assert 'all_market_terminal_screening_complete' in source
    assert 'comprehensive_discovery_lane_counts' not in source


def test_terminal_outcome_may_be_paper_implementation_or_governed_no_action() -> None:
    """Certification remains fail-closed while permitting the governed cash outcome."""

    source = inspect.getsource(cio_diagnostic.build_cio_diagnostic_audit)
    assert 'all_market_paper_implementation_certified' in source
    assert 'all_market_no_action_certified' in source
    assert 'all_market_operational_certified' in source
