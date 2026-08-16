"""Operational dispositions for the connectivity-control modules themselves."""
from __future__ import annotations

from governance.runtime_influence_registry import ComponentLifecycle
from governance.runtime_module_dispositions import RuntimeModuleDisposition


CONNECTIVITY_CONTROL_DISPOSITIONS: tuple[RuntimeModuleDisposition, ...] = (
    RuntimeModuleDisposition(
        "governance.runtime_module_dispositions",
        ComponentLifecycle.OPERATIONAL,
        "Release-audit configuration that classifies intentional non-live modules; it does not belong to the investment runtime.",
    ),
    RuntimeModuleDisposition(
        "governance.runtime_convergence_contracts",
        ComponentLifecycle.OPERATIONAL,
        "Release-audit influence contracts proving live global-rotation and historical-learning paths; no investment authority is created here.",
    ),
)

CONNECTIVITY_CONTROL_DISPOSITION_BY_NAME = {
    item.module: item for item in CONNECTIVITY_CONTROL_DISPOSITIONS
}


__all__ = [
    "CONNECTIVITY_CONTROL_DISPOSITION_BY_NAME",
    "CONNECTIVITY_CONTROL_DISPOSITIONS",
]
