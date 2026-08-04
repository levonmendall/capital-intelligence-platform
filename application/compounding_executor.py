"""Production executor binding for the compounding-first canonical cycle.

The existing production executor rebuilds a cycle after exact capability authority is
bound.  This wrapper keeps that safety behavior while ensuring the rebuilt cycle is
the compounding-aware subclass rather than silently falling back to the base cycle.
"""

from __future__ import annotations

import threading
from datetime import datetime

from application import production_context_contract as _contract
from application.compounding_cycle import CompoundingCanonicalCIOCycle
from application.production_context_executor import (
    ProductionCanonicalCIOExecutor as _ProductionCanonicalCIOExecutor,
)


_BINDING_LOCK = threading.RLock()


class CompoundingProductionCanonicalCIOExecutor(
    _ProductionCanonicalCIOExecutor
):
    """Preserve exact runtime authority while rebuilding a compounding cycle."""

    def run(self, *, as_of: datetime):
        with _BINDING_LOCK:
            original_cycle = _contract.CanonicalCIOCycle
            _contract.CanonicalCIOCycle = CompoundingCanonicalCIOCycle
            try:
                return super().run(as_of=as_of)
            finally:
                _contract.CanonicalCIOCycle = original_cycle


__all__ = ["CompoundingProductionCanonicalCIOExecutor"]
