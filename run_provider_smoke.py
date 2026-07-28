"""Run credential-safe live provider probes without granting certification."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import EODHDBindingRegistry, EODHDProvider, load_eodhd_bindings
from providers.fred import FREDProvider


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must be timezone-aware")
    return parsed


def _safe_error(error: Exception) -> str:
    message = str(error)
    for variable in (
        "FRED_API_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
        "CAPITAL_INTELLIGENCE_GLOBAL_MARKET_DATA_API_KEY",
        "CAPITAL_INTELLIGENCE_GLOBAL_REFERENCE_DATA_API_KEY",
        "CAPITAL_INTELLIGENCE_FIXED_INCOME_DATA_API_KEY",
    ):
        value = os.getenv(variable)
        if value:
            message = message.replace(value, "[REDACTED]")
    return message


def _write(path: str | None, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"
    if path is None:
        print(encoded, end="")
        return
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(destination)
    print(encoded, end="")


def _fred(series: tuple[str, ...]) -> dict[str, Any]:
    provider = FREDProvider()
    result: dict[str, Any] = {
        "provider": provider.name,
        "configured": provider.configured,
        "passed": False,
        "series": [],
    }
    if not provider.configured:
        result["error"] = "FRED_API_KEY is unavailable"
        return result
    observations = []
    try:
        for identifier in series:
            observation = provider.get_latest_value(identifier)
            observations.append(
                {
                    "series_identifier": identifier,
                    "observation_date": observation.date,
                    "value_available": True,
                    "realtime_start": observation.realtime_start,
                    "realtime_end": observation.realtime_end,
                }
            )
    except Exception as error:  # live provider boundary
        result["error"] = _safe_error(error)
        return result
    result["series"] = observations
    result["passed"] = len(observations) == len(series)
    return result


def _eodhd(as_of: datetime, binding_path: str | None) -> dict[str, Any]:
    path = binding_path or os.getenv("CAPITAL_INTELLIGENCE_EODHD_BINDINGS")
    registry = EODHDBindingRegistry(()) if not path else load_eodhd_bindings(path)
    provider = EODHDProvider(bindings=registry)
    result: dict[str, Any] = {
        "provider": provider.name,
        "configured": provider.configured,
        "passed": False,
        "binding_configured": bool(path),
    }
    if not provider.configured:
        result["error"] = "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN is unavailable"
        return result
    try:
        snapshot = provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
                provider_symbol="ACCOUNT",
                as_of=as_of,
                limit=1,
            )
        )
    except Exception as error:  # live provider boundary
        result["error"] = _safe_error(error)
        return result
    result.update(
        {
            "passed": True,
            "source_version": snapshot.source_version,
            "observed_at": snapshot.observed_at.isoformat(),
            "available_at": snapshot.available_at.isoformat(),
            "retrieved_at": snapshot.retrieved_at.isoformat(),
            "quality_state": snapshot.quality_state.value,
            "provider_record_id": snapshot.provider_record_id,
            "content_hash": snapshot.content_hash,
            "limitations": list(snapshot.limitations),
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of")
    parser.add_argument(
        "--fred-series",
        action="append",
        default=[],
        help="Official FRED series to probe; defaults to DFF, CPIAUCSL, and INDPRO.",
    )
    parser.add_argument("--eodhd-bindings")
    parser.add_argument("--require-fred", action="store_true")
    parser.add_argument("--require-eodhd", action="store_true")
    parser.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        as_of = _timestamp(args.as_of)
        series = tuple(args.fred_series or ("DFF", "CPIAUCSL", "INDPRO"))
        fred = _fred(series)
        eodhd = _eodhd(as_of, args.eodhd_bindings)
        blockers = []
        if args.require_fred and not fred["passed"]:
            blockers.append("required FRED probe did not pass")
        if args.require_eodhd and not eodhd["passed"]:
            blockers.append("required EODHD entitlement probe did not pass")
        payload = {
            "identifier": f"provider-smoke:{as_of.isoformat()}",
            "evaluated_at": as_of.isoformat(),
            "state": "passed" if not blockers else "blocked",
            "providers": [fred, eodhd],
            "blockers": blockers,
            "licensing_approved": False,
            "provider_certified": False,
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "secret_values_disclosed": False,
            "schema_version": "provider-smoke-report.v1",
        }
        _write(args.output, payload)
    except (OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": _safe_error(error),
                    "licensing_approved": False,
                    "provider_certified": False,
                    "paper_test_authorized": False,
                    "real_money_authorized": False,
                    "secret_values_disclosed": False,
                },
                sort_keys=True,
            )
        )
        return 4
    return 0 if not blockers else 3


if __name__ == "__main__":
    raise SystemExit(main())
