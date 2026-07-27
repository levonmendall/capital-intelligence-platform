"""Verify live FRED access without disclosing credentials."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Sequence

from providers.fred import FREDObservation, FREDProvider, FREDProviderError


_SERIES_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class FREDLiveProvider(Protocol):
    """Minimum provider surface required by the live smoke check."""

    @property
    def name(self) -> str:
        """Return the stable provider name."""

    @property
    def configured(self) -> bool:
        """Return whether provider credentials are configured."""

    def get_observations(
        self,
        series_id: str,
        limit: int = 24,
        sort_order: str = "desc",
    ) -> list[FREDObservation]:
        """Return recent observations from the live provider."""


def _series_id(value: str) -> str:
    normalized = value.strip().upper()
    if not _SERIES_PATTERN.fullmatch(normalized):
        raise ValueError("series_id contains unsupported characters")
    return normalized


def _aware_now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("checked_at must be timezone-aware")
    return resolved


def build_live_fred_report(
    provider: FREDLiveProvider,
    *,
    series_id: str,
    checked_at: datetime | None = None,
) -> dict[str, object]:
    """Execute one bounded live request and return a credential-safe report."""

    normalized_series = _series_id(series_id)
    if not provider.configured:
        raise FREDProviderError("FRED_API_KEY is not configured")
    observations = provider.get_observations(
        normalized_series,
        limit=3,
        sort_order="desc",
    )
    if not observations:
        raise FREDProviderError("FRED returned no usable observations")
    latest = observations[0]
    return {
        "schema_version": "fred-live-smoke.v1",
        "state": "ready",
        "provider": provider.name,
        "series_id": normalized_series,
        "checked_at": _aware_now(checked_at).isoformat(),
        "latest_observation_date": latest.date,
        "observation_count": len(observations),
        "credential_environment_variable": "FRED_API_KEY",
        "credential_configured": True,
        "live_request_completed": True,
        "secret_disclosed": False,
        "real_money_authorized": False,
    }


def safe_failure_report(
    *,
    series_id: str,
    error: Exception,
    checked_at: datetime | None = None,
) -> dict[str, object]:
    """Return a failure report without serializing exception text or secrets."""

    try:
        normalized_series = _series_id(series_id)
    except ValueError:
        normalized_series = "INVALID"
    return {
        "schema_version": "fred-live-smoke.v1",
        "state": "blocked",
        "provider": "FRED",
        "series_id": normalized_series,
        "checked_at": _aware_now(checked_at).isoformat(),
        "error_type": type(error).__name__,
        "detail": "live FRED verification failed; no credential value was logged",
        "credential_environment_variable": "FRED_API_KEY",
        "credential_configured": False,
        "live_request_completed": False,
        "secret_disclosed": False,
        "real_money_authorized": False,
    }


def _write(path: str, payload: dict[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--series",
        default="DGS10",
        help="Stable FRED series used for the bounded live request.",
    )
    parser.add_argument(
        "--report",
        default="reports/fred-live-smoke.json",
        help="Credential-safe JSON report path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = build_live_fred_report(
            FREDProvider(timeout=20),
            series_id=args.series,
        )
        exit_code = 0
    except (FREDProviderError, OSError, TypeError, ValueError) as error:
        payload = safe_failure_report(series_id=args.series, error=error)
        exit_code = 3
    _write(args.report, payload)
    print(json.dumps(payload, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
