"""Credential-readiness helpers shared by provider and presentation layers.

The helpers never return credential values and deliberately avoid including request URLs
or exception representations that can embed API keys.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


_PLACEHOLDER_MARKERS = (
    "paste_your",
    "paste-your",
    "replace_me",
    "replace-me",
    "your_api_key",
    "your-api-key",
    "your_secret",
    "your-secret",
    "change_me",
    "change-me",
    "changeme",
    "example",
    "dummy",
    "placeholder",
    "<api",
    "<key",
    "<secret",
)


@dataclass(frozen=True, slots=True)
class CredentialReadiness:
    """Safe, displayable readiness state for one provider."""

    provider: str
    state: str
    detail: str

    @property
    def configured(self) -> bool:
        return self.state == "configured"


def _value(values: Mapping[str, str], names: Sequence[str]) -> str:
    for name in names:
        raw = values.get(name)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def fred_credential_readiness(
    environ: Mapping[str, str] | None = None,
) -> CredentialReadiness:
    """Return whether a usable-looking FRED key is configured."""

    values = os.environ if environ is None else environ
    api_key = _value(values, ("FRED_API_KEY",))
    if not api_key:
        return CredentialReadiness(
            provider="FRED",
            state="missing",
            detail=(
                "FRED_API_KEY is not configured. Add a valid FRED API key to the "
                "deployment secrets and restart the service."
            ),
        )
    if _looks_like_placeholder(api_key):
        return CredentialReadiness(
            provider="FRED",
            state="placeholder",
            detail=(
                "FRED_API_KEY still contains a placeholder value. Replace it with a "
                "valid FRED API key in deployment secrets and restart the service."
            ),
        )
    return CredentialReadiness(
        provider="FRED",
        state="configured",
        detail="FRED credential is configured.",
    )


def alpaca_credential_readiness(
    environ: Mapping[str, str] | None = None,
) -> CredentialReadiness:
    """Return whether a usable-looking matching Alpaca paper key pair is configured."""

    values = os.environ if environ is None else environ
    key_id = _value(
        values,
        ("APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY"),
    )
    secret = _value(
        values,
        (
            "APCA_API_SECRET_KEY",
            "ALPACA_API_SECRET_KEY",
            "ALPACA_SECRET_KEY",
            "ALPACA_API_SECRET",
        ),
    )
    if not key_id or not secret:
        missing = []
        if not key_id:
            missing.append("APCA_API_KEY_ID")
        if not secret:
            missing.append("APCA_API_SECRET_KEY")
        return CredentialReadiness(
            provider="Alpaca",
            state="missing",
            detail=(
                f"Missing Alpaca paper credential(s): {', '.join(missing)}. Add a "
                "matching paper-account key pair to deployment secrets and restart "
                "the service."
            ),
        )
    if _looks_like_placeholder(key_id) or _looks_like_placeholder(secret):
        return CredentialReadiness(
            provider="Alpaca",
            state="placeholder",
            detail=(
                "The Alpaca paper key ID or secret still contains a placeholder value. "
                "Replace both with a matching paper-account key pair and restart the "
                "service."
            ),
        )
    return CredentialReadiness(
        provider="Alpaca",
        state="configured",
        detail="Alpaca paper credentials are configured.",
    )


def safe_provider_error(provider: str, error: BaseException) -> str:
    """Translate provider failures without exposing credentials or request URLs."""

    name = provider.strip().lower()
    text = str(error).lower()
    if name == "alpaca":
        if "401" in text:
            return (
                "Alpaca authentication failed (HTTP 401). Replace APCA_API_KEY_ID and "
                "APCA_API_SECRET_KEY with a matching Alpaca paper-account key pair, "
                "then restart the service."
            )
        if "403" in text:
            return (
                "Alpaca rejected the request (HTTP 403). Confirm the paper endpoint, "
                "IEX data feed, and paper-account permissions."
            )
        if "429" in text:
            return "Alpaca rate-limited the request (HTTP 429). Retry after the provider window resets."
        return "Alpaca paper-market evidence is unavailable. Review provider configuration and service logs."
    if name == "fred":
        if "400" in text or "401" in text or "api_key" in text or "api key" in text:
            return (
                "FRED authentication failed. Configure a valid FRED_API_KEY in "
                "deployment secrets and restart the service."
            )
        if "429" in text:
            return "FRED rate-limited the request. Retry after the provider window resets."
        return "FRED economic evidence is unavailable. Review provider configuration and service logs."
    return "Provider evidence is unavailable. Review deployment configuration and service logs."


__all__ = [
    "CredentialReadiness",
    "alpaca_credential_readiness",
    "fred_credential_readiness",
    "safe_provider_error",
]
