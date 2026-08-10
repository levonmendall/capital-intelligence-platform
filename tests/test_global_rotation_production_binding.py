from __future__ import annotations

import inspect

from application import compounding_executor
from application.global_rotation_cycle import GlobalOpportunityRotationCanonicalCIOCycle


def test_production_compounding_executor_binds_global_rotation_cycle() -> None:
    assert (
        compounding_executor.GlobalOpportunityRotationCanonicalCIOCycle
        is GlobalOpportunityRotationCanonicalCIOCycle
    )
    source = inspect.getsource(
        compounding_executor.CompoundingProductionCanonicalCIOExecutor.run
    )
    assert (
        "_contract.CanonicalCIOCycle = GlobalOpportunityRotationCanonicalCIOCycle"
        in source
    )
    assert "_contract.CanonicalCIOCycle = original_cycle" in source
    assert "MispricedChangeCanonicalCIOCycle" not in inspect.getsource(
        compounding_executor
    )
