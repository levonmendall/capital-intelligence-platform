"""Canonical Render-hosted Streamlit entrypoint."""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any, Callable

import streamlit as st

import app_impl
from secure_app import DeploymentContext, create_streamlit_application


_LOGGER = logging.getLogger("capital_intelligence.render_surfaces")
_RENDER_SURFACE_NAMES = (
    "_render_today",
    "_render_environment",
    "_render_portfolio",
    "_render_history",
)


def _synchronous_renderer(renderer: Callable[..., Any]) -> Callable[..., Any]:
    """Return the original callable beneath a Streamlit fragment wrapper."""

    return getattr(renderer, "__wrapped__", renderer)


def _guarded_renderer(
    surface_name: str,
    renderer: Callable[..., Any],
) -> Callable[..., Any]:
    """Render one surface synchronously and never leave a silent blank page."""

    target = _synchronous_renderer(renderer)

    @functools.wraps(target, updated=())
    def guarded(*args: Any, **kwargs: Any) -> Any:
        try:
            return target(*args, **kwargs)
        except Exception as error:
            _LOGGER.exception(
                "primary Streamlit surface failed to render: %s",
                surface_name,
            )
            st.error(
                "This surface could not be rendered. The application remains online "
                "and the failure has been recorded for diagnosis."
            )
            st.caption(
                f"Surface: {surface_name} · Error class: {type(error).__name__}"
            )
            return None

    guarded._capital_intelligence_guarded_surface = True  # type: ignore[attr-defined]
    guarded._capital_intelligence_fragment_removed = (  # type: ignore[attr-defined]
        target is not renderer
    )
    return guarded


def prepare_render_surface_runtime() -> None:
    """Replace auto-refresh fragments with stable full-run renderers on Render."""

    for attribute_name in _RENDER_SURFACE_NAMES:
        renderer = getattr(app_impl, attribute_name)
        if getattr(renderer, "_capital_intelligence_guarded_surface", False):
            continue
        guarded = _guarded_renderer(attribute_name.removeprefix("_render_"), renderer)
        if not getattr(guarded, "_capital_intelligence_fragment_removed", False):
            _LOGGER.warning(
                "surface renderer did not expose a fragment wrapper: %s",
                attribute_name,
            )
        setattr(app_impl, attribute_name, guarded)


def deployment_context_from_environment() -> DeploymentContext:
    release = (
        os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
        or os.getenv("RENDER_GIT_COMMIT")
        or "unknown"
    ).strip()
    return DeploymentContext(
        release=release,
        state_root=Path(
            os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
        ).expanduser(),
        render_host=os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip(),
    )


def main() -> None:
    prepare_render_surface_runtime()
    create_streamlit_application(deployment=deployment_context_from_environment())


if __name__ == "__main__":
    main()
