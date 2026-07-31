"""Credential-safe live provider validation for comprehensive market discovery.

This module proves that the production runtime can authenticate to required private
providers and retrieve current Yahoo chart evidence and completed-session Databento OPRA evidence without exposing
credentials or raw payloads.  It does not rank assets, construct a portfolio, authorize
orders, or enable real-money execution.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.databento import (
    DatabentoProvider,
    DatabentoProviderError,
    build_databento_provider,
)
from providers.databento_options import (
    DatabentoOptionsError,
    DatabentoOptionsProvider,
)
from providers.eodhd import EODHDProvider, EODHDProviderError

DEFAULT_PROVIDER_VALIDATION_REPORT = Path("database/provider-validation-report.json")
PROVIDER_VALIDATION_SCHEMA = "capital-intelligence-provider-validation.v1"


class ProviderValidationError(RuntimeError):
    """Raised when a required live provider cannot be validated."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _payload_count(payload: object) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, Mapping):
        return len(payload)
    return 0


@dataclass(frozen=True, slots=True)
class ProviderValidationCheck:
    name: str
    provider: str
    required: bool
    state: str
    detail: str
    observed_at: datetime
    source_identifier: str | None = None
    evidence_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("name", "provider", "state", "detail"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value.strip())
        if self.state not in {"passed", "failed", "skipped"}:
            raise ValueError("state must be passed, failed, or skipped")
        _aware(self.observed_at, field_name="observed_at")
        if self.source_identifier is not None:
            normalized = str(self.source_identifier).strip()
            object.__setattr__(self, "source_identifier", normalized or None)
        if self.evidence_fingerprint is not None:
            normalized = str(self.evidence_fingerprint).strip().lower()
            if normalized and len(normalized) != 64:
                raise ValueError("evidence_fingerprint must be a SHA-256 hex digest")
            object.__setattr__(self, "evidence_fingerprint", normalized or None)

    @property
    def passed(self) -> bool:
        return self.state == "passed"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "provider": self.provider,
            "required": self.required,
            "state": self.state,
            "detail": self.detail,
            "observed_at": self.observed_at.isoformat(),
            "source_identifier": self.source_identifier,
            "evidence_fingerprint": self.evidence_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class ProviderValidationReport:
    release: str
    generated_at: datetime
    checks: tuple[ProviderValidationCheck, ...]
    schema_version: str = PROVIDER_VALIDATION_SCHEMA

    def __post_init__(self) -> None:
        release = str(self.release).strip()
        if not release:
            raise ValueError("release cannot be empty")
        object.__setattr__(self, "release", release)
        _aware(self.generated_at, field_name="generated_at")
        if not self.checks:
            raise ValueError("checks cannot be empty")
        if not all(isinstance(item, ProviderValidationCheck) for item in self.checks):
            raise TypeError("checks must contain ProviderValidationCheck values")

    @property
    def ready(self) -> bool:
        return all(item.passed for item in self.checks if item.required)

    @property
    def failed_required_checks(self) -> tuple[str, ...]:
        return tuple(
            item.name for item in self.checks if item.required and not item.passed
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release": self.release,
            "generated_at": self.generated_at.isoformat(),
            "ready": self.ready,
            "failed_required_checks": list(self.failed_required_checks),
            "checks": [item.to_dict() for item in self.checks],
            "credentials_exposed": False,
            "real_money_authorized": False,
        }


HttpGet = Callable[..., Any]
Clock = Callable[[], datetime]


def _passed(
    *,
    name: str,
    provider: str,
    required: bool,
    detail: str,
    observed_at: datetime,
    source_identifier: str | None,
    evidence: object,
) -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider=provider,
        required=required,
        state="passed",
        detail=detail,
        observed_at=observed_at,
        source_identifier=source_identifier,
        evidence_fingerprint=_fingerprint(evidence),
    )


def _failed(
    *,
    name: str,
    provider: str,
    required: bool,
    detail: str,
    observed_at: datetime,
) -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider=provider,
        required=required,
        state="failed",
        detail=detail,
        observed_at=observed_at,
    )


def _skipped(
    *,
    name: str,
    provider: str,
    detail: str,
    observed_at: datetime,
) -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider=provider,
        required=False,
        state="skipped",
        detail=detail,
        observed_at=observed_at,
    )


def _validate_eodhd(
    provider: EODHDProvider,
    *,
    as_of: datetime,
) -> tuple[ProviderValidationCheck, ...]:
    if not provider.configured:
        return (
            _failed(
                name="eodhd_account_entitlement",
                provider="EODHD",
                required=True,
                detail="required EODHD API token is not configured",
                observed_at=as_of,
            ),
            _failed(
                name="eodhd_exchange_directory",
                provider="EODHD",
                required=True,
                detail="exchange-directory retrieval was not attempted without credentials",
                observed_at=as_of,
            ),
        )
    checks: list[ProviderValidationCheck] = []
    for name, dataset_type, symbol in (
        (
            "eodhd_account_entitlement",
            ProviderDatasetType.ACCOUNT_ENTITLEMENT,
            "ACCOUNT",
        ),
        (
            "eodhd_exchange_directory",
            ProviderDatasetType.EXCHANGE_DIRECTORY,
            "ALL",
        ),
    ):
        try:
            snapshot = provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=dataset_type,
                    provider_symbol=symbol,
                    as_of=as_of,
                    limit=100,
                )
            )
            count = _payload_count(snapshot.payload)
            if count < 1:
                raise EODHDProviderError("provider returned an empty governed payload")
            checks.append(
                _passed(
                    name=name,
                    provider="EODHD",
                    required=True,
                    detail=f"authenticated governed retrieval succeeded with {count} payload fields or records",
                    observed_at=snapshot.retrieved_at,
                    source_identifier=snapshot.provider_record_id,
                    evidence={
                        "content_hash": snapshot.content_hash,
                        "provider": snapshot.provider,
                        "source_version": snapshot.source_version,
                        "count": count,
                    },
                )
            )
        except (EODHDProviderError, OSError, TypeError, ValueError) as error:
            checks.append(
                _failed(
                    name=name,
                    provider="EODHD",
                    required=True,
                    detail=f"{type(error).__name__}: {error}",
                    observed_at=as_of,
                )
            )
    return tuple(checks)


def _yahoo_json(
    http_get: HttpGet,
    url: str,
    *,
    params: Mapping[str, object] | None = None,
) -> Mapping[str, Any]:
    response = http_get(
        url,
        params=dict(params or {}),
        headers={"User-Agent": "capital-intelligence-provider-validation/1.0"},
        timeout=20,
    )
    status = int(getattr(response, "status_code", 0))
    if status < 200 or status >= 300:
        raise ProviderValidationError(f"Yahoo HTTP {status}")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise ProviderValidationError("Yahoo returned a non-object JSON payload")
    return payload


def _validate_yahoo(
    http_get: HttpGet,
    *,
    as_of: datetime,
) -> tuple[tuple[ProviderValidationCheck, ...], float | None]:
    start = int((as_of - timedelta(days=10)).timestamp())
    end = int(as_of.timestamp())
    try:
        chart = _yahoo_json(
            http_get,
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY",
            params={
                "period1": start,
                "period2": end,
                "interval": "1d",
                "events": "history",
            },
        )
        result = chart["chart"]["result"]
        if not isinstance(result, list) or not result:
            raise ProviderValidationError("Yahoo chart result is empty")
        timestamps = result[0].get("timestamp", ())
        quote = result[0].get("indicators", {}).get("quote", ())[0]
        closes = tuple(float(item) for item in quote.get("close", ()) if item is not None)
        if not isinstance(timestamps, list) or not timestamps or not closes:
            raise ProviderValidationError("Yahoo chart observations are empty")
        latest_close = closes[-1]
        if latest_close <= 0.0:
            raise ProviderValidationError("Yahoo latest SPY close is not positive")
        return (
            (
                _passed(
                    name="yahoo_chart_evidence",
                    provider="YAHOO",
                    required=True,
                    detail=(
                        "public chart retrieval succeeded with "
                        f"{len(timestamps)} observations"
                    ),
                    observed_at=as_of,
                    source_identifier="yahoo-chart:SPY",
                    evidence={
                        "symbol": "SPY",
                        "timestamps": timestamps[-5:],
                        "latest_close": latest_close,
                    },
                ),
            ),
            latest_close,
        )
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        requests.RequestException,
        ProviderValidationError,
    ) as error:
        return (
            (
                _failed(
                    name="yahoo_chart_evidence",
                    provider="YAHOO",
                    required=True,
                    detail=f"{type(error).__name__}: {error}",
                    observed_at=as_of,
                ),
            ),
            None,
        )


def _validate_databento(
    provider: DatabentoProvider,
    options_provider: DatabentoOptionsProvider,
    *,
    as_of: datetime,
    underlying_price: float | None,
) -> tuple[ProviderValidationCheck, ...]:
    checks: list[ProviderValidationCheck] = []
    if not provider.configured:
        checks.append(
            _failed(
                name="databento_account_entitlement",
                provider="DATABENTO",
                required=True,
                detail="required Databento API key is not configured",
                observed_at=as_of,
            )
        )
    else:
        try:
            snapshot = provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
                    provider_symbol="ACCOUNT",
                    as_of=as_of,
                    limit=1_000,
                )
            )
            count = _payload_count(snapshot.payload)
            if count < 1:
                raise DatabentoProviderError(
                    "provider returned an empty dataset entitlement list"
                )
            checks.append(
                _passed(
                    name="databento_account_entitlement",
                    provider="DATABENTO",
                    required=True,
                    detail=(
                        "authenticated dataset discovery succeeded with "
                        f"{count} records"
                    ),
                    observed_at=snapshot.retrieved_at,
                    source_identifier=snapshot.provider_record_id,
                    evidence={
                        "content_hash": snapshot.content_hash,
                        "provider": snapshot.provider,
                        "source_version": snapshot.source_version,
                        "count": count,
                    },
                )
            )
        except (DatabentoProviderError, OSError, TypeError, ValueError) as error:
            checks.append(
                _failed(
                    name="databento_account_entitlement",
                    provider="DATABENTO",
                    required=True,
                    detail=f"{type(error).__name__}: {error}",
                    observed_at=as_of,
                )
            )
    if not options_provider.configured:
        detail = "required Databento OPRA credentials are not configured"
        checks.extend(
            (
                _failed(
                    name="databento_opra_definitions",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
                _failed(
                    name="databento_opra_daily_bars",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
            )
        )
        return tuple(checks)
    if underlying_price is None or underlying_price <= 0.0:
        detail = "current SPY reference price is unavailable for near-money OPRA validation"
        checks.extend(
            (
                _failed(
                    name="databento_opra_definitions",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
                _failed(
                    name="databento_opra_daily_bars",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
            )
        )
        return tuple(checks)
    try:
        proof = options_provider.validate_access(
            as_of=as_of,
            underlying_price=underlying_price,
        )
        checks.extend(
            (
                _passed(
                    name="databento_opra_definitions",
                    provider="DATABENTO",
                    required=True,
                    detail=(
                        "completed-session OPRA definition retrieval succeeded with "
                        f"{proof['definition_count']} contracts"
                    ),
                    observed_at=as_of,
                    source_identifier=(
                        f"databento-opra-definitions:SPY:{proof['session_date']}"
                    ),
                    evidence={
                        "dataset": proof["dataset"],
                        "session_date": proof["session_date"],
                        "definition_count": proof["definition_count"],
                        "eligible_definition_count": proof[
                            "eligible_definition_count"
                        ],
                    },
                ),
                _passed(
                    name="databento_opra_daily_bars",
                    provider="DATABENTO",
                    required=True,
                    detail=(
                        "production-aligned near-money OPRA retrieval succeeded with "
                        f"{proof['priced_sample_count']} priced contracts"
                    ),
                    observed_at=as_of,
                    source_identifier=(
                        f"databento-opra-bars:SPY:{proof['session_date']}"
                    ),
                    evidence={
                        "dataset": proof["dataset"],
                        "session_date": proof["session_date"],
                        "priced_sample_count": proof["priced_sample_count"],
                        "sample_symbols": proof["sample_symbols"],
                    },
                ),
            )
        )
    except (DatabentoOptionsError, OSError, TypeError, ValueError) as error:
        detail = f"{type(error).__name__}: {error}"
        checks.extend(
            (
                _failed(
                    name="databento_opra_definitions",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
                _failed(
                    name="databento_opra_daily_bars",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
            )
        )
    return tuple(checks)


def validate_live_providers(
    *,
    release: str | None = None,
    clock: Clock | None = None,
    http_get: HttpGet = requests.get,
    eodhd_provider: EODHDProvider | None = None,
    databento_provider: DatabentoProvider | None = None,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> ProviderValidationReport:
    """Run bounded live checks and return a credential-safe evidence report."""

    generated_at = _aware(
        (clock or (lambda: datetime.now(timezone.utc)))(),
        field_name="clock",
    )
    resolved_release = (
        release
        or os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
        or os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("GITHUB_SHA")
        or "unknown"
    )
    eodhd = eodhd_provider or EODHDProvider(clock=lambda: generated_at)
    if databento_provider is None:
        try:
            databento = build_databento_provider()
        except (DatabentoProviderError, OSError, TypeError, ValueError):
            databento = DatabentoProvider()
    else:
        databento = databento_provider
    databento_options = (
        databento_options_provider or DatabentoOptionsProvider()
    )
    yahoo_checks, spy_reference_price = _validate_yahoo(
        http_get,
        as_of=generated_at,
    )
    checks = (
        *_validate_eodhd(eodhd, as_of=generated_at),
        *yahoo_checks,
        *_validate_databento(
            databento,
            databento_options,
            as_of=generated_at,
            underlying_price=spy_reference_price,
        ),
    )
    return ProviderValidationReport(
        release=str(resolved_release),
        generated_at=generated_at,
        checks=tuple(checks),
    )


def provider_validation_report_path(
    value: str | Path | None = None,
) -> Path:
    if value is not None:
        return Path(value).expanduser()
    configured = os.getenv("CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_REPORT", "").strip()
    if configured:
        return Path(configured).expanduser()
    data_root = os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if data_root:
        return Path(data_root).expanduser() / "provider-validation-report.json"
    return DEFAULT_PROVIDER_VALIDATION_REPORT


def write_provider_validation_report(
    report: ProviderValidationReport,
    path: str | Path | None = None,
) -> Path:
    target = provider_validation_report_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def load_provider_validation_report(
    path: str | Path | None = None,
) -> dict[str, object] | None:
    target = provider_validation_report_path(path)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != PROVIDER_VALIDATION_SCHEMA:
        return None
    return payload


def require_provider_validation(report: ProviderValidationReport) -> None:
    if report.ready:
        return
    failed = ", ".join(report.failed_required_checks) or "unknown required check"
    raise ProviderValidationError(f"required live provider validation failed: {failed}")


__all__ = [
    "DEFAULT_PROVIDER_VALIDATION_REPORT",
    "PROVIDER_VALIDATION_SCHEMA",
    "ProviderValidationCheck",
    "ProviderValidationError",
    "ProviderValidationReport",
    "load_provider_validation_report",
    "provider_validation_report_path",
    "require_provider_validation",
    "validate_live_providers",
    "write_provider_validation_report",
]
