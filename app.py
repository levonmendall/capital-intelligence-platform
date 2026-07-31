"""Canonical local Streamlit entrypoint."""

from __future__ import annotations

from secure_app import create_streamlit_application


def main() -> None:
    create_streamlit_application()


if __name__ == "__main__":
    main()
