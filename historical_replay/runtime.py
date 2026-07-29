"""Persistent historical backfill loop for the always-on application host."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from .backfill import coordinator_from_config, ten_year_window


def run_once() -> dict[str, object]:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    root = Path(os.getenv("CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR", str(data_dir / "historical_replay")))
    config = os.getenv("CAPITAL_INTELLIGENCE_HISTORICAL_CONFIG", "config/historical_replay_free_sources.json")
    user_agent = os.getenv("SEC_USER_AGENT", "").strip() or os.getenv(
        "CAPITAL_INTELLIGENCE_HISTORICAL_USER_AGENT",
        "Capital-Intelligence-Platform historical-research contact=repository-owner",
    )
    max_records = int(os.getenv("CAPITAL_INTELLIGENCE_HISTORICAL_MAX_RECORDS_PER_SOURCE", "100000"))
    start, end = ten_year_window()
    coordinator = coordinator_from_config(config_path=config, data_root=root, user_agent=user_agent)
    return coordinator.run(start=start, end=end, max_records_per_source=max_records).as_dict()


def run_loop() -> int:
    interval = int(os.getenv("CAPITAL_INTELLIGENCE_HISTORICAL_INTERVAL_SECONDS", "86400"))
    if interval < 3600:
        raise ValueError("historical interval must be at least one hour")
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            print(json.dumps({"event": "historical_backfill_completed", "report": run_once()}, sort_keys=True), flush=True)
        except Exception as exc:
            print(json.dumps({"event": "historical_backfill_failed", "error": str(exc), "real_money_authorized": False}, sort_keys=True), flush=True)
        deadline = time.monotonic() + interval
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(30, max(0.1, deadline - time.monotonic())))
    return 0
