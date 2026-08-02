"""Compatibility package for the active comprehensive-discovery implementation.

Python prefers this package over the adjacent module file. The package loads that
module under a private name, re-exports its public contract, and forwards mutations of
provider/catalog helper seams to the archived provider implementation. This preserves
existing monkeypatch and injected-probe behavior while the active module owns the new
preselection architecture.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_ACTIVE_NAME = "operations._comprehensive_market_discovery_active"
_ACTIVE_PATH = Path(__file__).resolve().parent.parent / "comprehensive_market_discovery.py"

_active = sys.modules.get(_ACTIVE_NAME)
if _active is None:
    spec = importlib.util.spec_from_file_location(_ACTIVE_NAME, _ACTIVE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load active comprehensive discovery from {_ACTIVE_PATH}")
    _active = importlib.util.module_from_spec(spec)
    sys.modules[_ACTIVE_NAME] = _active
    spec.loader.exec_module(_active)

_SKIP = {
    "__name__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__cached__",
}
for _name, _value in vars(_active).items():
    if _name not in _SKIP:
        globals()[_name] = _value

__all__ = tuple(getattr(_active, "__all__", ()))
_FORWARDED_HELPERS = frozenset(
    {"_catalog_from_eodhd", "_futures_catalog", "_option_catalog"}
)


class _ForwardingDiscoveryModule(ModuleType):
    """Keep helper injection bound to the active and legacy implementations."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name not in _FORWARDED_HELPERS:
            return
        setattr(_active, name, value)
        legacy = getattr(_active, "_legacy", None)
        if legacy is not None:
            setattr(legacy, name, value)


sys.modules[__name__].__class__ = _ForwardingDiscoveryModule
