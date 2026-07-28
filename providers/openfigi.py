"""Free OpenFIGI v3 identifier-mapping adapter.

OpenFIGI is supporting identity evidence only.  It cannot satisfy the platform's
historical-security-master, listing-history, delisting, corporate-action, or
complete-universe requirements by itself.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from data import IdentifierScheme, InstrumentIdentifier
from data.provider import ProviderError


OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"


class OpenFigiProviderError(ProviderError):
    """Raised when OpenFIGI cannot return a valid mapping response."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} cannot be empty")
    return result


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class OpenFigiMappingJob:
    """One bounded third-party identifier mapping request."""

    id_type: str
    id_value: str
    exchange_code: str | None = None
    mic_code: str | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id_type",
            _text(self.id_type, field_name="id_type").upper(),
        )
        object.__setattr__(
            self,
            "id_value",
            _text(self.id_value, field_name="id_value"),
        )
        for field_name in ("exchange_code", "mic_code", "currency"):
            value = _optional_text(getattr(self, field_name), field_name=field_name)
            if value is not None:
                value = value.upper()
            object.__setattr__(self, field_name, value)
        if self.exchange_code is not None and self.mic_code is not None:
            raise ValueError("exchange_code and mic_code cannot both be supplied")

    def to_payload(self) -> dict[str, str]:
        value = {"idType": self.id_type, "idValue": self.id_value}
        if self.exchange_code is not None:
            value["exchCode"] = self.exchange_code
        if self.mic_code is not None:
            value["micCode"] = self.mic_code
        if self.currency is not None:
            value["currency"] = self.currency
        return value


@dataclass(frozen=True, slots=True)
class OpenFigiInstrumentMatch:
    """One OpenFIGI mapping match with provider-native metadata."""

    figi: str
    ticker: str | None
    name: str | None
    exchange_code: str | None
    market_sector: str | None
    security_type: str | None
    security_type_2: str | None
    composite_figi: str | None
    share_class_figi: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "figi", _text(self.figi, field_name="figi").upper())
        for field_name in (
            "ticker",
            "name",
            "exchange_code",
            "market_sector",
            "security_type",
            "security_type_2",
            "composite_figi",
            "share_class_figi",
        ):
            value = _optional_text(getattr(self, field_name), field_name=field_name)
            if value is not None and field_name in {
                "ticker",
                "exchange_code",
                "composite_figi",
                "share_class_figi",
            }:
                value = value.upper()
            object.__setattr__(self, field_name, value)

    @property
    def identifiers(self) -> tuple[InstrumentIdentifier, ...]:
        values = [
            InstrumentIdentifier(
                scheme=IdentifierScheme.FIGI,
                value=self.figi,
                provider="OPENFIGI",
            )
        ]
        if self.ticker is not None:
            values.append(
                InstrumentIdentifier(
                    scheme=IdentifierScheme.TICKER,
                    value=self.ticker,
                    provider="OPENFIGI",
                )
            )
        for value in (self.composite_figi, self.share_class_figi):
            if value is not None and value != self.figi:
                values.append(
                    InstrumentIdentifier(
                        scheme=IdentifierScheme.FIGI,
                        value=value,
                        provider="OPENFIGI",
                    )
                )
        return tuple(values)

    @classmethod
    def from_payload(cls, value: object) -> "OpenFigiInstrumentMatch":
        if not isinstance(value, dict) or not value.get("figi"):
            raise OpenFigiProviderError("OpenFIGI returned a malformed instrument match")
        return cls(
            figi=str(value["figi"]),
            ticker=None if value.get("ticker") is None else str(value["ticker"]),
            name=None if value.get("name") is None else str(value["name"]),
            exchange_code=(
                None if value.get("exchCode") is None else str(value["exchCode"])
            ),
            market_sector=(
                None
                if value.get("marketSector") is None
                else str(value["marketSector"])
            ),
            security_type=(
                None
                if value.get("securityType") is None
                else str(value["securityType"])
            ),
            security_type_2=(
                None
                if value.get("securityType2") is None
                else str(value["securityType2"])
            ),
            composite_figi=(
                None
                if value.get("compositeFIGI") is None
                else str(value["compositeFIGI"])
            ),
            share_class_figi=(
                None
                if value.get("shareClassFIGI") is None
                else str(value["shareClassFIGI"])
            ),
        )


@dataclass(frozen=True, slots=True)
class OpenFigiMappingResult:
    job: OpenFigiMappingJob
    matches: tuple[OpenFigiInstrumentMatch, ...]
    retrieved_at: datetime
    warning: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.job, OpenFigiMappingJob):
            raise TypeError("job must be OpenFigiMappingJob")
        if not isinstance(self.matches, tuple) or not all(
            isinstance(item, OpenFigiInstrumentMatch) for item in self.matches
        ):
            raise TypeError("matches must contain OpenFigiInstrumentMatch values")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        object.__setattr__(
            self,
            "warning",
            _optional_text(self.warning, field_name="warning"),
        )


class OpenFigiProvider:
    """Map identifiers through the free OpenFIGI v3 API."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 20,
        *,
        clock: Callable[[], datetime] | None = None,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENFIGI_API_KEY")
        self.timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._http_post = http_post or requests.post

    @property
    def name(self) -> str:
        return "OPENFIGI_V3"

    @property
    def configured(self) -> bool:
        """OpenFIGI permits anonymous access; a key only raises rate limits."""

        return True

    @property
    def authenticated(self) -> bool:
        return bool(self.api_key)

    @property
    def maximum_jobs_per_request(self) -> int:
        return 100 if self.authenticated else 5

    def map_identifiers(
        self,
        jobs: tuple[OpenFigiMappingJob, ...],
    ) -> tuple[OpenFigiMappingResult, ...]:
        if not isinstance(jobs, tuple) or not jobs:
            raise ValueError("jobs must be a non-empty tuple")
        if not all(isinstance(item, OpenFigiMappingJob) for item in jobs):
            raise TypeError("jobs must contain OpenFigiMappingJob values")
        if len(jobs) > self.maximum_jobs_per_request:
            raise OpenFigiProviderError(
                f"OpenFIGI request exceeds the {self.maximum_jobs_per_request}-job limit"
            )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        try:
            response = self._http_post(
                OPENFIGI_MAPPING_URL,
                json=[item.to_payload() for item in jobs],
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise OpenFigiProviderError("OpenFIGI mapping request failed") from error
        status_code = int(getattr(response, "status_code", 0))
        if status_code < 200 or status_code >= 300:
            raise OpenFigiProviderError(f"OpenFIGI returned HTTP {status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise OpenFigiProviderError("OpenFIGI returned invalid JSON") from error
        if not isinstance(payload, list) or len(payload) != len(jobs):
            raise OpenFigiProviderError(
                "OpenFIGI response does not align with the requested mapping jobs"
            )
        retrieved_at = self._now()
        results: list[OpenFigiMappingResult] = []
        for job, item in zip(jobs, payload, strict=True):
            if not isinstance(item, dict):
                raise OpenFigiProviderError("OpenFIGI returned a malformed job result")
            error = item.get("error")
            if error:
                raise OpenFigiProviderError(
                    "OpenFIGI rejected a mapping job: " + str(error)
                )
            data = item.get("data", [])
            if not isinstance(data, list):
                raise OpenFigiProviderError("OpenFIGI mapping data must be an array")
            matches = tuple(OpenFigiInstrumentMatch.from_payload(value) for value in data)
            warning = None if item.get("warning") is None else str(item["warning"])
            results.append(
                OpenFigiMappingResult(
                    job=job,
                    matches=matches,
                    retrieved_at=retrieved_at,
                    warning=warning,
                )
            )
        return tuple(results)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise OpenFigiProviderError("OpenFIGI clock must be timezone-aware")
        return value


__all__ = [
    "OPENFIGI_MAPPING_URL",
    "OpenFigiInstrumentMatch",
    "OpenFigiMappingJob",
    "OpenFigiMappingResult",
    "OpenFigiProvider",
    "OpenFigiProviderError",
]
