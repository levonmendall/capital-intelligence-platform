"""Production cycle-binding regression tests."""
from __future__ import annotations

import inspect

import application.compounding_executor as compounding_executor
from application.global_rotation_cycle import GlobalOpportunityRotationCanonicalCIOCycle


def test_compounding_executor_explicitly_selects_global_rotation_cycle() -> None:
    assert (
        compounding_executor.CompoundingProductionCanonicalCIOExecutor.cycle_factory
        is GlobalOpportunityRotationCanonicalCIOCycle
    )


def test_compounding_executor_does_not_mutate_production_cycle_globals() -> None:
    source = inspect.getsource(compounding_executor)
    assert "CanonicalCIOCycle =" not in source
    assert "threading" not in source
    assert "_BINDING_LOCK" not in source
