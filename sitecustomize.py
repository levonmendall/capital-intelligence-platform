"""Normalize deployment release metadata before application modules import.

Python imports ``sitecustomize`` during interpreter startup when the repository root
is on ``sys.path``. Render exposes the deployed commit as ``RENDER_GIT_COMMIT``, while
canonical CIO persistence reads ``CAPITAL_INTELLIGENCE_CODE_VERSION``. This adapter
bridges those provider-specific names without overriding an explicit governed value.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping


_RELEASE_SOURCE_KEYS = (
    "RENDER_GIT_COMMIT",
    "GITHUB_SHA",
    "SOURCE_VERSION",
    "COMMIT_SHA",
    "GIT_COMMIT",
)
_TARGET_KEY = "CAPITAL_INTELLIGENCE_CODE_VERSION"


def configure_code_version(
    environment: MutableMapping[str, str] | None = None,
) -> str | None:
    """Populate the canonical code-version variable from deployment metadata."""

    values = os.environ if environment is None else environment
    existing = str(values.get(_TARGET_KEY, "")).strip()
    if existing:
        return existing
    for key in _RELEASE_SOURCE_KEYS:
        candidate = str(values.get(key, "")).strip()
        if candidate:
            values[_TARGET_KEY] = candidate
            return candidate
    return None


configure_code_version()


__all__ = ["configure_code_version"]
