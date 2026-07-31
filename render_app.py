"""Canonical Render-hosted Streamlit entrypoint."""

from __future__ import annotations

import os
from pathlib import Path

from secure_app import DeploymentContext, create_streamlit_application


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
    create_streamlit_application(deployment=deployment_context_from_environment())


if __name__ == "__main__":
    main()
