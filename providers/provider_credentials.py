"""Credential-safe connectivity probes for configured market-data providers.

These probes establish only that a configured credential can authenticate and return
structurally valid supporting evidence. They do not grant data licensing approval,
provider certification, paper-execution authority, or real-money authority.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests


class ProviderCredentialProbeError(RuntimeError):
    """Raised when a provider credential cannot return valid probe evidence."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class EnvironmentCredential:
    """One selected non-empty environment credential alias."""

    name: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, field_name="name"))
        object.__setattr__(self, "value", _text(self.value, field_name="value"))


def environment_credential(*names: str) -> EnvironmentCredential | None:
    """Return the first configured alias without exposing its value."""

    for name in names:
        normalized_name = _text(name, field_name="environment name")
        value = os.getenv(normalized_name)
        if isinstance(value, str) and value.strip():
            return EnvironmentCredential(name=normalized_name, value=value.strip())
    return None


def configured_environment_names(*names: str) -> tuple[str, ...]:
    """Return configured alias names only, never secret values."""

    return tuple(
        name
        for name in names
        if isinstance(os.getenv(name), str) and bool(os.getenv(name, "").strip())
    )


def _json_response(response: Any, *, provider: str) -> Any:
    status_code = int(getattr(response, "status_code", 0))
    if status_code < 200 or status_code >= 300:
        raise ProviderCredentialProbeError(
            f"{provider} returned HTTP {status_code or 'unknown'}"
        )
    try:
        return response.json()
    except (TypeError, ValueError) as error:
        raise ProviderCredentialProbeError(
            f"{provider} returned invalid JSON"
        ) from error


class AlphaVantageCredentialProbe:
    """Validate an Alpha Vantage key with a bounded global-quote request."""

    environment_names = (
        "ALPHAVANTAGE_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
    )
    endpoint = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: int = 20,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = _text(api_key, field_name="api_key")
        self.timeout = timeout
        self._http_get = http_get or requests.get

    def probe(self) -> dict[str, Any]:
        try:
            response = self._http_get(
                self.endpoint,
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": "IBM",
                    "apikey": self.api_key,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ProviderCredentialProbeError(
                "Alpha Vantage request failed"
            ) from error
        payload = _json_response(response, provider="Alpha Vantage")
        if not isinstance(payload, dict):
            raise ProviderCredentialProbeError(
                "Alpha Vantage response must be an object"
            )
        for field in ("Error Message", "Information", "Note"):
            if payload.get(field):
                raise ProviderCredentialProbeError(
                    f"Alpha Vantage returned a provider notice in {field}"
                )
        quote = payload.get("Global Quote")
        if not isinstance(quote, dict) or str(quote.get("01. symbol", "")).upper() != "IBM":
            raise ProviderCredentialProbeError(
                "Alpha Vantage did not return the expected IBM quote"
            )
        if not str(quote.get("05. price", "")).strip():
            raise ProviderCredentialProbeError(
                "Alpha Vantage quote did not contain a price"
            )
        return {
            "probe": "GLOBAL_QUOTE",
            "symbol": "IBM",
            "price_available": True,
            "execution_authority": False,
        }


class TwelveDataCredentialProbe:
    """Validate a Twelve Data key with a bounded quote request."""

    environment_names = (
        "TWELVE_API_KEY",
        "TWELVE_DATA_API_KEY",
    )
    endpoint = "https://api.twelvedata.com/quote"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: int = 20,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = _text(api_key, field_name="api_key")
        self.timeout = timeout
        self._http_get = http_get or requests.get

    def probe(self) -> dict[str, Any]:
        try:
            response = self._http_get(
                self.endpoint,
                params={"symbol": "AAPL", "apikey": self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ProviderCredentialProbeError(
                "Twelve Data request failed"
            ) from error
        payload = _json_response(response, provider="Twelve Data")
        if not isinstance(payload, dict):
            raise ProviderCredentialProbeError("Twelve Data response must be an object")
        if str(payload.get("status", "")).lower() == "error" or payload.get("code"):
            raise ProviderCredentialProbeError("Twelve Data rejected the quote request")
        if str(payload.get("symbol", "")).upper() != "AAPL":
            raise ProviderCredentialProbeError(
                "Twelve Data did not return the expected AAPL quote"
            )
        if not str(payload.get("close") or payload.get("price") or "").strip():
            raise ProviderCredentialProbeError(
                "Twelve Data quote did not contain a price"
            )
        return {
            "probe": "quote",
            "symbol": "AAPL",
            "price_available": True,
            "execution_authority": False,
        }


class DatabentoCredentialProbe:
    """Validate a Databento key through the historical metadata service."""

    environment_names = (
        "DATABENTO_API_KEY",
        "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
    )
    endpoint = "https://hist.databento.com/v0/metadata.list_datasets"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: int = 20,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = _text(api_key, field_name="api_key")
        self.timeout = timeout
        self._http_get = http_get or requests.get

    def probe(self) -> dict[str, Any]:
        try:
            response = self._http_get(
                self.endpoint,
                auth=(self.api_key, ""),
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ProviderCredentialProbeError("Databento request failed") from error
        payload = _json_response(response, provider="Databento")
        if not isinstance(payload, list) or not payload:
            raise ProviderCredentialProbeError(
                "Databento did not return an available dataset list"
            )
        datasets = tuple(
            str(item).strip()
            for item in payload
            if isinstance(item, str) and item.strip()
        )
        if not datasets:
            raise ProviderCredentialProbeError(
                "Databento dataset list did not contain valid identifiers"
            )
        return {
            "probe": "metadata.list_datasets",
            "dataset_count": len(datasets),
            "dataset_sample": list(datasets[:5]),
            "execution_authority": False,
        }


__all__ = [
    "AlphaVantageCredentialProbe",
    "DatabentoCredentialProbe",
    "EnvironmentCredential",
    "ProviderCredentialProbeError",
    "TwelveDataCredentialProbe",
    "configured_environment_names",
    "environment_credential",
]
