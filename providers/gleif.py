"""Free GLEIF legal-entity reference-data adapter.

GLEIF evidence establishes legal-entity identity and selected relationships.  It is
supporting reference evidence only and does not constitute a tradable-instrument,
listing-history, corporate-action, market-price, or complete security-master feed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from data import IdentifierScheme, InstrumentIdentifier, Issuer
from data.provider import ProviderError


GLEIF_LEI_RECORD_URL = "https://api.gleif.org/api/v1/lei-records/{lei}"


class GleifProviderError(ProviderError):
    """Raised when GLEIF cannot return a valid legal-entity record."""


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


def _nested(value: object, *keys: str) -> object | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


@dataclass(frozen=True, slots=True)
class GleifEntityRecord:
    """One current GLEIF Golden Copy legal-entity record."""

    lei: str
    legal_name: str
    entity_status: str | None
    registration_status: str | None
    legal_jurisdiction: str | None
    legal_address_country: str | None
    headquarters_country: str | None
    bic_codes: tuple[str, ...]
    retrieved_at: datetime
    provider_record_id: str
    content_hash: str
    source_version: str = "gleif-api.v1.current"

    def __post_init__(self) -> None:
        object.__setattr__(self, "lei", _text(self.lei, field_name="lei").upper())
        if len(self.lei) != 20 or not self.lei.isalnum():
            raise ValueError("lei must be a 20-character alphanumeric identifier")
        object.__setattr__(
            self,
            "legal_name",
            _text(self.legal_name, field_name="legal_name"),
        )
        for field_name in (
            "entity_status",
            "registration_status",
            "legal_jurisdiction",
            "legal_address_country",
            "headquarters_country",
        ):
            value = _optional_text(getattr(self, field_name), field_name=field_name)
            if value is not None:
                value = value.upper()
            object.__setattr__(self, field_name, value)
        if not isinstance(self.bic_codes, tuple):
            raise TypeError("bic_codes must be a tuple")
        normalized_bics = tuple(
            _text(item, field_name="bic_code").upper() for item in self.bic_codes
        )
        if len(normalized_bics) != len(set(normalized_bics)):
            raise ValueError("bic_codes cannot contain duplicates")
        object.__setattr__(self, "bic_codes", normalized_bics)
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        object.__setattr__(
            self,
            "provider_record_id",
            _text(self.provider_record_id, field_name="provider_record_id"),
        )
        object.__setattr__(
            self,
            "content_hash",
            _text(self.content_hash, field_name="content_hash").lower(),
        )
        if len(self.content_hash) != 64:
            raise ValueError("content_hash must be a SHA-256 digest")
        object.__setattr__(
            self,
            "source_version",
            _text(self.source_version, field_name="source_version"),
        )

    @property
    def issuer(self) -> Issuer:
        identifiers = [
            InstrumentIdentifier(
                scheme=IdentifierScheme.PROVIDER,
                value=f"LEI:{self.lei}",
                provider="GLEIF",
            )
        ]
        identifiers.extend(
            InstrumentIdentifier(
                scheme=IdentifierScheme.PROVIDER,
                value=f"BIC:{bic}",
                provider="GLEIF",
            )
            for bic in self.bic_codes
        )
        return Issuer(
            issuer_id=f"GLEIF:LEI:{self.lei}",
            name=self.legal_name,
            identifiers=tuple(identifiers),
        )


class GleifProvider:
    """Retrieve current legal-entity evidence from the public GLEIF API."""

    def __init__(
        self,
        timeout: int = 20,
        *,
        clock: Callable[[], datetime] | None = None,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._http_get = http_get or requests.get

    @property
    def name(self) -> str:
        return "GLEIF"

    @property
    def configured(self) -> bool:
        return True

    def fetch_lei(self, lei: str) -> GleifEntityRecord:
        normalized = _text(lei, field_name="lei").upper()
        if len(normalized) != 20 or not normalized.isalnum():
            raise ValueError("lei must be a 20-character alphanumeric identifier")
        try:
            response = self._http_get(
                GLEIF_LEI_RECORD_URL.format(lei=normalized),
                headers={"Accept": "application/vnd.api+json"},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise GleifProviderError("GLEIF LEI request failed") from error
        status_code = int(getattr(response, "status_code", 0))
        if status_code < 200 or status_code >= 300:
            raise GleifProviderError(f"GLEIF returned HTTP {status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise GleifProviderError("GLEIF returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise GleifProviderError("GLEIF returned an invalid JSON:API document")
        data = payload["data"]
        record_id = str(data.get("id") or normalized).upper()
        if record_id != normalized:
            raise GleifProviderError("GLEIF returned a different LEI than requested")
        attributes = data.get("attributes")
        if not isinstance(attributes, dict):
            raise GleifProviderError("GLEIF record is missing attributes")
        legal_name = _nested(attributes, "entity", "legalName", "name")
        if legal_name is None:
            raise GleifProviderError("GLEIF record is missing the entity legal name")
        raw_bics = attributes.get("bic")
        bic_codes = (
            tuple(str(item) for item in raw_bics if isinstance(item, str) and item.strip())
            if isinstance(raw_bics, list)
            else ()
        )
        canonical = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return GleifEntityRecord(
            lei=normalized,
            legal_name=str(legal_name),
            entity_status=(
                None
                if _nested(attributes, "entity", "status") is None
                else str(_nested(attributes, "entity", "status"))
            ),
            registration_status=(
                None
                if _nested(attributes, "registration", "status") is None
                else str(_nested(attributes, "registration", "status"))
            ),
            legal_jurisdiction=(
                None
                if _nested(attributes, "entity", "legalJurisdiction") is None
                else str(_nested(attributes, "entity", "legalJurisdiction"))
            ),
            legal_address_country=(
                None
                if _nested(attributes, "entity", "legalAddress", "country") is None
                else str(_nested(attributes, "entity", "legalAddress", "country"))
            ),
            headquarters_country=(
                None
                if _nested(attributes, "entity", "headquartersAddress", "country")
                is None
                else str(
                    _nested(
                        attributes,
                        "entity",
                        "headquartersAddress",
                        "country",
                    )
                )
            ),
            bic_codes=bic_codes,
            retrieved_at=self._now(),
            provider_record_id=record_id,
            content_hash=hashlib.sha256(canonical).hexdigest(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise GleifProviderError("GLEIF clock must be timezone-aware")
        return value


__all__ = [
    "GLEIF_LEI_RECORD_URL",
    "GleifEntityRecord",
    "GleifProvider",
    "GleifProviderError",
]
