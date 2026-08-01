"""Canonical local Streamlit entrypoint."""

from __future__ import annotations

import app_impl
import secure_app
import ui_refinement
from secure_app import create_streamlit_application


def main() -> None:
    ui_refinement.install(app_impl, secure_app)
    create_streamlit_application()


if __name__ == "__main__":
    main()
