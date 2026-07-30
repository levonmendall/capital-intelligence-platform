"""Persistent historical backfill and canonical replay loop."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from .backfill import coordinator_from_config, ten_year_window
from .canonical import HistoricalCanonicalContextBuilder
from .canonical_runtime_v5 import MacroCompleteCanonicalHistoricalReplayEngine
from .store import HistoricalStore


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def run_once() -> dict[str, object]:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    root = Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR",
            str(data_dir / "historical_replay"),
        )
    )
    config = os.getenv(
        "CAPITAL_INTELLIGENCE_HISTORICAL_CONFIG",
        "config/historical_replay_free_sources.json",
    )
    user_agent = os.getenv("SEC_USER_AGENT", "").strip() or os.getenv(
        "CAPITAL_INTELLIGENCE_HISTORICAL_USER_AGENT",
        "Capital-Intelligence-Platform historical-research contact=repository-owner",
    )
    max_records = int(
        os.getenv(
            "CAPITAL_INTELLIGENCE_HISTORICAL_MAX_RECORDS_PER_SOURCE",
            "100000",
        )
    )
    start, end = ten_year_window()
    coordinator = coordinator_from_config(
        config_path=config,
        data_root=root,
        user_agent=user_agent,
    )
    payload = coordinator.run(
        start=start,
        end=end,
        max_records_per_source=max_records,
    ).as_dict()

    if _boolean(
        "CAPITAL_INTELLIGENCE_CANONICAL_HISTORICAL_REPLAY_ENABLED",
        True,
    ):
        try:
            report = MacroCompleteCanonicalHistoricalReplayEngine(
                HistoricalStore(root),
                builder=HistoricalCanonicalContextBuilder(
                    minimum_observations=int(
                        os.getenv(
                            "CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_MINIMUM_OBSERVATIONS",
                            "63",
                        )
                    ),
                    maximum_candidates=int(
                        os.getenv(
                            "CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_MAXIMUM_CANDIDATES",
                            "25",
                        )
                    ),
                ),
            ).run(
                start=start,
                end=end,
                cadence=os.getenv(
                    "CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_CADENCE",
                    "monthly",
                ),
                strict_only=_boolean(
                    "CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_STRICT_ONLY",
                    False,
                ),
                initial_portfolio_value=float(
                    os.getenv(
                        "CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_INITIAL_VALUE",
                        "250000",
                    )
                ),
            )
            certification_ready = report.get("certification_ready") is True
            payload["canonical_replay"] = {
                "state": "available" if certification_ready else "blocked",
                "runtime_version": report.get("runtime_version"),
                "archive_scan_count": report.get("archive_scan_count"),
                "relevant_record_count": report.get("relevant_record_count"),
                "canonical_cio_invoked_count": report[
                    "canonical_cio_invoked_count"
                ],
                "blocked_cutoff_count": report["blocked_cutoff_count"],
                "decision_cutoff_count": report["decision_cutoff_count"],
                "ending_portfolio_value": report["ending_portfolio_value"],
                "strict_replay": report["strict_replay"],
                "macro_coverage_satisfied": report.get(
                    "macro_coverage_satisfied"
                )
                is True,
                "certification_ready": certification_ready,
                "calibration_eligible_observation_count": int(
                    report.get("calibration_eligible_observation_count", 0) or 0
                ),
                "learning_manifest": str(
                    root / "manifests" / "latest-canonical-learning.json"
                ),
                "research_only": True,
                "execution_authorized": False,
                "real_money_authorized": False,
            }
        except Exception as error:
            payload["canonical_replay"] = {
                "state": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
                "research_only": True,
                "execution_authorized": False,
                "real_money_authorized": False,
            }
    return payload


def run_loop() -> int:
    interval = int(
        os.getenv("CAPITAL_INTELLIGENCE_HISTORICAL_INTERVAL_SECONDS", "86400")
    )
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
            print(
                json.dumps(
                    {
                        "event": "historical_learning_completed",
                        "report": run_once(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "historical_learning_failed",
                        "error": str(exc),
                        "real_money_authorized": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        deadline = time.monotonic() + interval
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(30, max(0.1, deadline - time.monotonic())))
    return 0
