"""Validate configured provider secrets against real credential-safe endpoints.

The command never prints secret values and grants no provider certification,
paper-execution authority, or real-money authority.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.alpaca_paper import (
    AlpacaPaperProviderError,
    create_alpaca_paper_client,
)
from providers.eodhd import EODHDProvider
from providers.fred import FREDProvider
from providers.openfigi import OpenFigiMappingJob, OpenFigiProvider
from providers.provider_credentials import (
    AlphaVantageCredentialProbe,
    DatabentoCredentialProbe,
    ProviderCredentialProbeError,
    TwelveDataCredentialProbe,
)


ALPACA_KEY_NAMES = (
    "APCA_API_KEY_ID",
    "ALPACA_API_KEY_ID",
    "ALPACA_API_KEY",
)
ALPACA_SECRET_NAMES = (
    "APCA_API_SECRET_KEY",
    "ALPACA_API_SECRET_KEY",
    "ALPACA_SECRET_KEY",
    "ALPACA_API_SECRET",
)
FRED_NAMES = ("FRED_API_KEY",)
EODHD_NAMES = (
    "EODHD_API_KEY",
    "EODHD_API_TOKEN",
    "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
)
OPENFIGI_NAMES = (
    "OPEN_FIGI_API_KEY",
    "OPENFIGI_API_KEY",
)
ALL_SECRET_NAMES = tuple(
    dict.fromkeys(
        ALPACA_KEY_NAMES
        + ALPACA_SECRET_NAMES
        + FRED_NAMES
        + EODHD_NAMES
        + OPENFIGI_NAMES
        + AlphaVantageCredentialProbe.environment_names
        + DatabentoCredentialProbe.environment_names
        + TwelveDataCredentialProbe.environment_names
    )
)


def _configured_values(names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        value = os.getenv(name)
        normalized = value.strip() if isinstance(value, str) else ""
        if normalized and normalized not in seen:
            result.append((name, normalized))
            seen.add(normalized)
    return tuple(result)


def _safe_error(error: Exception) -> str:
    message = str(error) or type(error).__name__
    for name in ALL_SECRET_NAMES:
        value = os.getenv(name)
        if isinstance(value, str) and value:
            message = message.replace(value, "[REDACTED]")
    return message


def _base_result(
    provider: str,
    credential_names: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "provider": provider,
        "configured": bool(credential_names),
        "passed": False,
        "credential_names": list(credential_names),
        "selected_credential": None,
        "evidence": {},
        "provider_certified": False,
        "paper_test_authorized": False,
        "real_money_authorized": False,
    }


def _try_single_credentials(
    provider: str,
    names: tuple[str, ...],
    probe: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    candidates = _configured_values(names)
    result = _base_result(provider, tuple(name for name, _value in candidates))
    if not candidates:
        result["error"] = "no supported credential alias is configured"
        return result
    errors: list[str] = []
    for name, value in candidates:
        try:
            evidence = probe(value)
        except Exception as error:  # live provider boundary
            errors.append(f"{name}: {_safe_error(error)}")
            continue
        result.update(
            {
                "passed": True,
                "selected_credential": name,
                "evidence": evidence,
            }
        )
        return result
    result["error"] = "; ".join(errors) or "no configured credential authenticated"
    return result


def _alpaca() -> dict[str, Any]:
    key_names = tuple(name for name, _value in _configured_values(ALPACA_KEY_NAMES))
    secret_names = tuple(
        name for name, _value in _configured_values(ALPACA_SECRET_NAMES)
    )
    result = _base_result("alpaca-paper", key_names + secret_names)
    result["configured"] = bool(key_names and secret_names)
    if not result["configured"]:
        result["error"] = "a complete Alpaca paper key ID and secret pair is required"
        return result
    try:
        client = create_alpaca_paper_client()
        account = client.account()
    except (AlpacaPaperProviderError, TypeError, ValueError) as error:
        result["error"] = _safe_error(error)
        return result
    status = str(account.get("status", "unavailable")).upper()
    if status != "ACTIVE":
        result["error"] = f"Alpaca paper account status is {status}"
        return result
    result.update(
        {
            "passed": True,
            "selected_credential": "authenticated-key-secret-pair",
            "evidence": {
                "account_status": status,
                "paper_endpoint": True,
                "data_feed": client.settings.data_feed.lower(),
                "order_submission_tested": False,
            },
        }
    )
    return result


def _fred() -> dict[str, Any]:
    def probe(value: str) -> dict[str, Any]:
        observation = FREDProvider(api_key=value).get_latest_value("DGS10")
        return {
            "series_identifier": "DGS10",
            "observation_date": observation.date,
            "value_available": True,
        }

    return _try_single_credentials("fred", FRED_NAMES, probe)


def _eodhd(as_of: datetime) -> dict[str, Any]:
    def probe(value: str) -> dict[str, Any]:
        snapshot = EODHDProvider(api_token=value).fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
                provider_symbol="ACCOUNT",
                as_of=as_of,
                limit=1,
            )
        )
        return {
            "probe": "account-entitlement",
            "source_version": snapshot.source_version,
            "quality_state": snapshot.quality_state.value,
            "content_hash": snapshot.content_hash,
        }

    return _try_single_credentials("eodhd", EODHD_NAMES, probe)


def _openfigi() -> dict[str, Any]:
    def probe(value: str) -> dict[str, Any]:
        results = OpenFigiProvider(api_key=value).map_identifiers(
            (
                OpenFigiMappingJob(
                    id_type="ID_BB_GLOBAL",
                    id_value="BBG000B9XRY4",
                ),
            )
        )
        matches = results[0].matches
        if not matches:
            raise ProviderCredentialProbeError(
                "OpenFIGI returned no mapping matches"
            )
        return {
            "probe": "v3-mapping",
            "requested_identifier": "BBG000B9XRY4",
            "match_count": len(matches),
            "authenticated_rate_limit": True,
        }

    return _try_single_credentials("openfigi", OPENFIGI_NAMES, probe)


def _alpha_vantage() -> dict[str, Any]:
    return _try_single_credentials(
        "alpha-vantage",
        AlphaVantageCredentialProbe.environment_names,
        lambda value: AlphaVantageCredentialProbe(value).probe(),
    )


def _databento() -> dict[str, Any]:
    return _try_single_credentials(
        "databento",
        DatabentoCredentialProbe.environment_names,
        lambda value: DatabentoCredentialProbe(value).probe(),
    )


def _twelve_data() -> dict[str, Any]:
    return _try_single_credentials(
        "twelve-data",
        TwelveDataCredentialProbe.environment_names,
        lambda value: TwelveDataCredentialProbe(value).probe(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Return nonzero unless every supported provider credential passes.",
    )
    return parser


def _write(path: str | None, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path is not None:
        destination = Path(path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(destination)
    print(encoded, end="")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evaluated_at = datetime.now(timezone.utc)
    try:
        providers = [
            _alpaca(),
            _fred(),
            _eodhd(evaluated_at),
            _openfigi(),
            _alpha_vantage(),
            _databento(),
            _twelve_data(),
        ]
        blockers = [
            f"{item['provider']}: {item.get('error', 'probe did not pass')}"
            for item in providers
            if args.require_all and not item["passed"]
        ]
        payload = {
            "identifier": f"provider-secret-validation:{evaluated_at.isoformat()}",
            "evaluated_at": evaluated_at.isoformat(),
            "state": "passed" if not blockers else "blocked",
            "providers": providers,
            "configured_provider_count": sum(
                1 for item in providers if item["configured"]
            ),
            "passed_provider_count": sum(1 for item in providers if item["passed"]),
            "blockers": blockers,
            "secret_values_disclosed": False,
            "provider_certification_granted": False,
            "paper_test_authorized": False,
            "execution_authority_granted": False,
            "real_money_authorized": False,
            "schema_version": "provider-secret-validation.v1",
        }
        _write(args.output, payload)
    except Exception as error:  # defensive command boundary
        _write(
            args.output,
            {
                "state": "blocked",
                "error": _safe_error(error),
                "secret_values_disclosed": False,
                "provider_certification_granted": False,
                "paper_test_authorized": False,
                "execution_authority_granted": False,
                "real_money_authorized": False,
            },
        )
        return 4
    return 0 if not blockers else 3


if __name__ == "__main__":
    raise SystemExit(main())
