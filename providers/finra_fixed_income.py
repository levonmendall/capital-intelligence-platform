"""Credential-safe FINRA fixed-income API access.

FINRA API Platform credentials use OAuth 2.0 client credentials.  This adapter proves
that the configured client ID/secret can obtain a short-lived token and access the
public Fixed Income Query API.  It does not persist or expose tokens, does not claim
per-security TRACE pricing where only aggregate datasets are available, and grants no
execution authority.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

import requests

from provider_environment import provider_environment_value


FINRA_TOKEN_ENDPOINT = (
    "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token"
)
FINRA_FIXED_INCOME_BASE_URL = "https://api.finra.org/data/group/fixedIncomeMarket/name"
FINRA_TREASURY_DAILY_AGGREGATES = "treasuryDailyAggregates"


class FinraFixedIncomeError(RuntimeError):
    """Raised when FINRA authentication or fixed-income evidence cannot be validated."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


@dataclass(frozen=True, slots=True)
class FinraFixedIncomeProbeEvidence:
    dataset: str
    record_available: bool
    trade_date_available: bool
    token_type: str
    expires_in_seconds: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "record_available": self.record_available,
            "trade_date_available": self.trade_date_available,
            "token_type": self.token_type,
            "expires_in_seconds": self.expires_in_seconds,
            "credential_values_included": False,
            "execution_authority": False,
        }


class FinraFixedIncomeProvider:
    """Bounded FINRA OAuth + Fixed Income Query API client."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        timeout_seconds: int = 20,
        http_post: Callable[..., Any] | None = None,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self._client_id = _text(client_id, field_name="client_id")
        self._client_secret = _text(client_secret, field_name="client_secret")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise TypeError("timeout_seconds must be an integer")
        if timeout_seconds < 1 or timeout_seconds > 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        self._timeout_seconds = timeout_seconds
        self._http_post = http_post or requests.post
        self._http_get = http_get or requests.get

    def _access_token(self) -> tuple[str, str, int | None]:
        try:
            response = self._http_post(
                FINRA_TOKEN_ENDPOINT,
                params={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"Accept": "application/json"},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as error:
            raise FinraFixedIncomeError("FINRA OAuth request failed") from error
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise FinraFixedIncomeError(
                f"FINRA OAuth returned HTTP {status or 'unknown'}",
                status_code=status or None,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise FinraFixedIncomeError("FINRA OAuth returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise FinraFixedIncomeError("FINRA OAuth response must be an object")
        token = payload.get("access_token")
        token_type = str(payload.get("token_type", "Bearer")).strip() or "Bearer"
        if not isinstance(token, str) or not token.strip():
            raise FinraFixedIncomeError("FINRA OAuth response missing access token")
        try:
            expires = int(payload.get("expires_in")) if payload.get("expires_in") is not None else None
        except (TypeError, ValueError):
            expires = None
        return token.strip(), token_type, expires

    def probe_treasury_daily_aggregates(self) -> FinraFixedIncomeProbeEvidence:
        """Prove configured credentials can read a production fixed-income dataset."""

        token, token_type, expires = self._access_token()
        endpoint = f"{FINRA_FIXED_INCOME_BASE_URL}/{FINRA_TREASURY_DAILY_AGGREGATES}"
        try:
            response = self._http_get(
                endpoint,
                params={"limit": 1},
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as error:
            raise FinraFixedIncomeError("FINRA Fixed Income request failed") from error
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise FinraFixedIncomeError(
                f"FINRA Fixed Income returned HTTP {status or 'unknown'}",
                status_code=status or None,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise FinraFixedIncomeError("FINRA Fixed Income returned invalid JSON") from error
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise FinraFixedIncomeError("FINRA Fixed Income response must be a list")
        if not payload or not isinstance(payload[0], Mapping):
            raise FinraFixedIncomeError("FINRA Fixed Income returned no aggregate evidence")
        first = payload[0]
        trade_date = first.get("tradeDate")
        if not isinstance(trade_date, str) or not trade_date.strip():
            raise FinraFixedIncomeError("FINRA Treasury aggregate missing tradeDate")
        return FinraFixedIncomeProbeEvidence(
            dataset=FINRA_TREASURY_DAILY_AGGREGATES,
            record_available=True,
            trade_date_available=True,
            token_type=token_type,
            expires_in_seconds=expires,
        )


def build_finra_fixed_income_provider(
    environment: Mapping[str, str] | None = None,
) -> FinraFixedIncomeProvider | None:
    """Build FINRA from any supported client-ID/secret alias, if both are configured."""

    source = os.environ if environment is None else environment
    client_id = provider_environment_value(
        "FINRA_CLIENT_ID",
        "CAPITAL_INTELLIGENCE_FINRA_CLIENT_ID",
        environment=source,
    )
    client_secret = provider_environment_value(
        "FINRA_CLIENT_SECRET",
        "CAPITAL_INTELLIGENCE_FINRA_CLIENT_SECRET",
        environment=source,
    )
    if client_id is None and client_secret is None:
        return None
    if client_id is None or client_secret is None:
        raise FinraFixedIncomeError(
            "FINRA requires both client ID and client secret"
        )
    return FinraFixedIncomeProvider(client_id, client_secret)


__all__ = [
    "FINRA_FIXED_INCOME_BASE_URL",
    "FINRA_TOKEN_ENDPOINT",
    "FINRA_TREASURY_DAILY_AGGREGATES",
    "FinraFixedIncomeError",
    "FinraFixedIncomeProbeEvidence",
    "FinraFixedIncomeProvider",
    "build_finra_fixed_income_provider",
]
