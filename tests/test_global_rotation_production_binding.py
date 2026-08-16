from __future__ import annotations

import inspect

from application import compounding_executor
from application.global_rotation_cycle import GlobalOpportunityRotationCanonicalCIOCycle


def test_production_compounding_executor_binds_global_rotation_cycle() -> None:
    assert (
        compounding_executor.CompoundingProductionCanonicalCIOExecutor.cycle_factory
        is GlobalOpportunityRotationCanonicalCIOCycle
    )
    source = inspect.getsource(compounding_executor)
    assert "cycle_factory = GlobalOpportunityRotationCanonicalCIOCycle" in source
    assert "_contract.CanonicalCIOCycle" not in source
    assert "MispricedChangeCanonicalCIOCycle" not in source
