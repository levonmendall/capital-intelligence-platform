"""Canonical reporting-time formatting for presentation-only UI surfaces."""

from __future__ import annotations

import os
from datetime import datetime, timezone, tzinfo
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_DEFAULT_TIMEZONE = "UTC"


def reporting_timezone(values: Mapping[str, str] | None = None) -> tzinfo:
    """Resolve the configured reporting timezone without changing evidence timestamps."""

    resolved = os.environ if values is None else values
    name = str(
        resolved.get("CAPITAL_INTELLIGENCE_PAPER_REPORT_TIMEZONE")
        or resolved.get("CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE")
        or _DEFAULT_TIMEZONE
    ).strip()
    try:
        return ZoneInfo(name or _DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return timezone.utc


def format_reporting_timestamp(
    value: object,
    *,
    missing: str,
    values: Mapping[str, str] | None = None,
) -> str:
    """Render an ISO timestamp in the configured report timezone, preserving fail-safe UTC."""

    text = str(value or "").strip()
    if not text:
        return missing
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    rendered = parsed.astimezone(reporting_timezone(values))
    return rendered.strftime("%b %d, %-I:%M %p %Z")


__all__ = ["format_reporting_timestamp", "reporting_timezone"]