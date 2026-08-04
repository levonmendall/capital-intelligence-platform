"""Production executor preserving exact authority for the investor cycle."""

from __future__ import annotations

import threading
from datetime import datetime

from application import production_context_contract as _contract
from application.investor_cycle import InvestorCanonicalCIOCycle
from application.production_context_executor import (
    ProductionCanonicalCIOExecutor as _ProductionCanonicalCIOExecutor,
)


_BINDING_LOCK = threading.RLock()


class InvestorProductionCanonicalCIOExecutor(_ProductionCanonicalCIOExecutor):
    def run(self, *, as_of: datetime):
        with _BINDING_LOCK:
            original = _contract.CanonicalCIOCycle
            _contract.CanonicalCIOCycle = InvestorCanonicalCIOCycle
            try:
                return super().run(as_of=as_of)
            finally:
                _contract.CanonicalCIOCycle = original


__all__ = ["InvestorProductionCanonicalCIOExecutor"]
