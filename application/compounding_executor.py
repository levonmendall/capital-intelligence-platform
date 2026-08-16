"""Production executor binding for the global adaptive compounding cycle.

The production executor rebuilds a canonical cycle after exact capability authority is
bound. This wrapper preserves that safety behavior while selecting the global
opportunity-rotation cycle explicitly. CIO-only authority, independent construction,
fail-closed point-in-time evidence, and paper-only execution remain unchanged.
"""
from __future__ import annotations

from application.global_rotation_cycle import GlobalOpportunityRotationCanonicalCIOCycle
from application.production_context_executor import (
    ProductionCanonicalCIOExecutor as _ProductionCanonicalCIOExecutor,
)


class CompoundingProductionCanonicalCIOExecutor(_ProductionCanonicalCIOExecutor):
    """Select the governed global-rotation cycle for production rebuilds."""

    cycle_factory = GlobalOpportunityRotationCanonicalCIOCycle


__all__ = ["CompoundingProductionCanonicalCIOExecutor"]
