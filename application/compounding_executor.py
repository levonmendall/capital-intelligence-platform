"""Production executor binding for the compounding-first canonical cycle.

The existing production executor rebuilds a cycle after exact capability authority is
bound. This wrapper keeps that safety behavior while ensuring the rebuilt cycle uses
the compounding-aware mispriced-change subclass rather than silently falling back to
the base cycle. The added synthesis is advisory evidence for the existing six
specialists; it cannot change candidate authority, CIO thresholds, construction, or
paper-only execution controls.
"""

from __future__ import annotations

import threading
from datetime import datetime

from application import production_context_contract as _contract
from application.mispriced_change_cycle import MispricedChangeCanonicalCIOCycle
from application.production_context_executor import (
    ProductionCanonicalCIOExecutor as _ProductionCanonicalCIOExecutor,
)


_BINDING_LOCK = threading.RLock()


class CompoundingProductionCanonicalCIOExecutor(
    _ProductionCanonicalCIOExecutor
):
    """Preserve exact runtime authority while rebuilding the adaptive compounding cycle."""

    def run(self, *, as_of: datetime):
        with _BINDING_LOCK:
            original_cycle = _contract.CanonicalCIOCycle
            _contract.CanonicalCIOCycle = MispricedChangeCanonicalCIOCycle
            try:
                return super().run(as_of=as_of)
            finally:
                _contract.CanonicalCIOCycle = original_cycle


__all__ = ["CompoundingProductionCanonicalCIOExecutor"]
