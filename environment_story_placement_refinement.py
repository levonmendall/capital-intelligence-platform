"""Compatibility shim for the retired duplicate Environment process grid.

Environment now teaches through the structural macro-and-market dashboard
installed by ``surface_content_refinement``. The former four-card process diagram
repeated the page's classification language and is intentionally no longer
injected above the content.
"""

from __future__ import annotations

from types import ModuleType


_INSTALLED_STATE_KEY = "_capital_intelligence_environment_story_placement_retired"


def install(app_impl: ModuleType) -> None:
    """Record installation without mutating the active Environment renderer."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
