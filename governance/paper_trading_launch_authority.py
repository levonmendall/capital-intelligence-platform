"""Strict latest-assessment semantics for paper-trading launch authorization."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from governance.paper_trading_launch import (
    PaperTradingLaunchReport,
    SQLitePaperTradingLaunchStore as _BaseLaunchStore,
    _aware,
    _text,
)


class SQLitePaperTradingLaunchStore(_BaseLaunchStore):
    """Use only the latest exact-baseline assessment as launch authority.

    A newer blocked or expired assessment supersedes every older ready report. The
    authority never searches backward for a more favorable conclusion.
    """

    def latest_ready(
        self,
        *,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        as_of: datetime,
    ) -> PaperTradingLaunchReport | None:
        baseline = _text(baseline_identifier, field_name="baseline_identifier")
        process = _text(process_version, field_name="process_version")
        code = _text(code_version, field_name="code_version")
        timestamp = _aware(as_of, field_name="as_of")
        self.verify_integrity()
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                f"""
                SELECT payload_json FROM {self._TABLE}
                WHERE baseline_identifier = ? AND process_version = ?
                  AND code_version = ? AND assessed_at <= ?
                ORDER BY sequence DESC LIMIT 1
                """,
                (baseline, process, code, timestamp.isoformat()),
            ).fetchone()
        if row is None:
            return None
        report = PaperTradingLaunchReport.from_dict(json.loads(str(row[0])))
        return (
            report
            if report.active_at(
                as_of=timestamp,
                baseline_identifier=baseline,
                process_version=process,
                code_version=code,
            )
            else None
        )


__all__ = ["SQLitePaperTradingLaunchStore"]
