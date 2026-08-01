"""Render-hosted Streamlit entrypoint with resilient opportunity-scan status."""

from __future__ import annotations


def main() -> None:
    import opportunity_scan_resilience

    opportunity_scan_resilience.install()

    import render_app

    render_app.main()


if __name__ == "__main__":
    main()
