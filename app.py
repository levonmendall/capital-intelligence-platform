"""Canonical local Streamlit entrypoint."""

from __future__ import annotations

import opportunity_scan_resilience
import public_event_recency_runtime
import today_event_alignment_runtime
from secure_app import create_streamlit_application
from ui_runtime_composition import install_canonical_surface_composition


def main() -> None:
    public_event_recency_runtime.install()
    today_event_alignment_runtime.install()
    opportunity_scan_resilience.install()
    install_canonical_surface_composition(
        include_decision_pulse=True,
        include_history_refinement=False,
        replace_story_fragments=True,
    )
    create_streamlit_application()


if __name__ == "__main__":
    main()
