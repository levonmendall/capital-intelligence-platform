"""Apply complete CIO-report enrichment to the canonical full-report export path.

The full report's authenticated download route builds its own exact-lineage decision
bundle.  This adapter ensures that bundle receives the same read-only cycle-level
completeness enrichment as the Portfolio report path.  It cannot alter evidence,
rank candidates, change CIO authority, size or construct positions, execute trades,
or authorize real money.
"""

from __future__ import annotations

from functools import wraps
from types import ModuleType
from typing import Any, Mapping

import cio_report_completeness_enrichment


_INSTALLED_STATE_KEY = "_capital_intelligence_canonical_cio_export_enrichment_installed"


def install(session_navigation: ModuleType) -> None:
    """Enrich every canonical full-report decision bundle exactly once."""

    if getattr(session_navigation, _INSTALLED_STATE_KEY, False):
        return

    original = session_navigation._decision_bundle

    @wraps(original)
    def decision_bundle(
        app: ModuleType,
        *,
        briefing: Mapping[str, Any] | None,
        construction: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        bundle = original(
            app,
            briefing=briefing,
            construction=construction,
        )
        return cio_report_completeness_enrichment.enrich_report_bundle(app, bundle)

    session_navigation._decision_bundle = decision_bundle
    setattr(session_navigation, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
