"""Authenticated production API for Capital Intelligence.

Keep the package boundary lazy.  Operational workers frequently need only
``api.config.ApiSettings``; importing the complete FastAPI route graph in those
processes retains an avoidable application working set during memory-bounded CIO
diagnostics.  The public package exports remain unchanged and are resolved on first
access.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from api.app import create_app
    from api.config import ApiSettings
    from api.repositories import ApiResources, build_resources
    from security import AuthenticationService, SQLiteIdentityStore

__all__ = [
    "ApiResources",
    "ApiSettings",
    "AuthenticationService",
    "SQLiteIdentityStore",
    "build_resources",
    "create_app",
]


_EXPORT_MODULES = {
    "ApiResources": "api.repositories",
    "ApiSettings": "api.config",
    "AuthenticationService": "security",
    "SQLiteIdentityStore": "security",
    "build_resources": "api.repositories",
    "create_app": "api.app",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
