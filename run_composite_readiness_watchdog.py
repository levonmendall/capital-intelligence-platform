"""Make Render process health fail when composite readiness remains blocked."""

from __future__ import annotations

import json
import os
import time
from typing import Callable

import httpx


def run_watchdog(
    *,
    probe: Callable[[], bool],
    startup_grace_seconds: int,
    poll_seconds: int,
    consecutive_failures: int,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    if startup_grace_seconds < 0 or poll_seconds < 1 or consecutive_failures < 1:
        raise ValueError("invalid composite readiness watchdog policy")
    deadline = clock() + startup_grace_seconds
    ever_ready = False
    failures = 0
    while True:
        try:
            ready = bool(probe())
        except (httpx.HTTPError, OSError, TypeError, ValueError):
            ready = False
        if ready:
            ever_ready = True
            failures = 0
        else:
            failures += 1
            if (ever_ready or clock() >= deadline) and failures >= consecutive_failures:
                return 1
        sleeper(poll_seconds)


def _http_probe() -> bool:
    response = httpx.get(
        "http://127.0.0.1:8000/ready",
        headers={"host": "localhost", "x-forwarded-proto": "https"},
        timeout=10.0,
        follow_redirects=True,
    )
    if response.status_code != 200:
        return False
    payload = response.json()
    return payload.get("ready") is True and bool(payload.get("deployed_git_sha"))


def main() -> int:
    result = run_watchdog(
        probe=_http_probe,
        startup_grace_seconds=int(
            os.getenv("CAPITAL_INTELLIGENCE_READINESS_STARTUP_GRACE_SECONDS", "900")
        ),
        poll_seconds=int(
            os.getenv("CAPITAL_INTELLIGENCE_READINESS_POLL_SECONDS", "15")
        ),
        consecutive_failures=int(
            os.getenv("CAPITAL_INTELLIGENCE_READINESS_FAILURE_THRESHOLD", "3")
        ),
    )
    print(
        json.dumps(
            {
                "event": "composite_readiness_watchdog_stopped",
                "exit_code": result,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
