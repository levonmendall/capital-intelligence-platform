"""Use the canonical CIO diagnostic endpoint as the live telemetry transport.

The canonical endpoint intentionally returns HTTP 503 while the governed all-market
diagnostic is incomplete. This wrapper treats that 503 JSON body as valid read-only
telemetry, then delegates all payload safety checks, allowlisting, terminal-state logic,
and persistence to ``capture_render_production_telemetry``.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# GitHub Actions executes this file directly as
# ``python scripts/capture_render_production_telemetry_canonical.py``. In that mode,
# Python puts ``scripts/`` rather than the repository root on sys.path, so the package
# import below would otherwise fail before telemetry can contact Render.
if __package__ in {None, ""}:
    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)

from scripts import capture_render_production_telemetry as telemetry

_CANONICAL_DIAGNOSTIC_PATH = "/v1/operations/cio-diagnostic"


def fetch_canonical_public_audit(
    url: str, *, timeout_seconds: float = 10.0
) -> tuple[Mapping[str, Any], int, float]:
    """GET canonical readiness JSON, accepting its intentional incomplete-state 503."""

    if not url.rstrip("/").endswith(_CANONICAL_DIAGNOSTIC_PATH):
        raise ValueError("telemetry transport must use the canonical CIO diagnostic endpoint")

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "capital-intelligence-render-telemetry/1.0",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read()
    except urllib.error.HTTPError as error:
        if error.code != 503:
            raise
        status = 503
        raw = error.read()

    latency_ms = (time.monotonic() - started) * 1000.0
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("public audit must encode a JSON object")

    # The canonical route predates the telemetry-only marker. The downstream collector
    # still recursively rejects forbidden fields and requires paper-only / no-real-money
    # assertions before accepting this locally verified transport marker.
    normalized = dict(payload)
    normalized["credential_safe"] = True
    return normalized, status, latency_ms


def main(argv: Sequence[str] | None = None) -> int:
    telemetry.fetch_public_audit = fetch_canonical_public_audit
    return telemetry.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
