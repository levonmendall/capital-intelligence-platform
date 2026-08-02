"""Compatibility shim for the retired duplicate Today process grid.

Today now teaches through the ranked market-story presentation installed by
``surface_content_refinement``. The former four-card process diagram repeated the
same concepts already expressed by the page and is intentionally no longer
injected above the content.
"""

from __future__ import annotations

from types import ModuleType


_INSTALLED_STATE_KEY = "_capital_intelligence_today_story_placement_retired"


def install(app_impl: ModuleType) -> None:
    """Record installation without mutating the active Today renderer."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
