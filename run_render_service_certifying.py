"""Start Render after priming truthful exact-release diagnostic state."""

from __future__ import annotations

from typing import Sequence

from prime_release_cio_diagnostic import prime_release_diagnostic_request
from run_render_service_nonblocking import run_nonblocking_render_service


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError("run_render_service_certifying.py accepts no arguments")
    primer_status = prime_release_diagnostic_request()
    if primer_status != 0:
        return primer_status
    return run_nonblocking_render_service()


if __name__ == "__main__":
    raise SystemExit(main())
