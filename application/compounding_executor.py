"""Production executor binding for the global adaptive compounding cycle.

The production executor rebuilds a canonical cycle after exact capability authority is
bound. This wrapper preserves that safety behavior while selecting the global
opportunity-rotation cycle. CIO-only authority, independent construction, fail-closed
point-in-time evidence, and paper-only execution remain unchanged.
"""
from __future__ import annotations

import threading
from datetime import datetime

from application import production_context_contract as _contract
from application.global_rotation_cycle import GlobalOpportunityRotationCanonicalCIOCycle
from application.production_context_executor import (
    ProductionCanonicalCIOExecutor as _ProductionCanonicalCIOExecutor,
)

_BINDING_LOCK = threading.RLock()


class CompoundingProductionCanonicalCIOExecutor(_ProductionCanonicalCIOExecutor):
    """Preserve runtime authority while rebuilding the adaptive rotation cycle."""

    def run(self, *, as_of: datetime):
        with _BINDING_LOCK:
            original_cycle = _contract.CanonicalCIOCycle
            _contract.CanonicalCIOCycle = GlobalOpportunityRotationCanonicalCIOCycle
            try:
                return super().run(as_of=as_of)
            finally:
                _contract.CanonicalCIOCycle = original_cycle


__all__ = ["CompoundingProductionCanonicalCIOExecutor"]
