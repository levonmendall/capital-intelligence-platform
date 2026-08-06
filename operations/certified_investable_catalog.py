"""Certified provider-neutral instrument catalogs for universal market discovery.

A deployment may publish every instrument it can identify, evidence, and paper-execute
through the optional external catalog contract.  In addition, the repository's governed
multi-venue crypto bindings are a built-in capability catalog: only spot pairs carrying
both Coinbase and Kraken identifiers may enter the direct-crypto discovery lane.

The comprehensive discovery process merges these records before screening and applies
no asset-count or asset-class shortlist.  Missing, malformed, incomplete, stale, or
duplicate configured records fail closed rather than silently shrinking market scope.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from providers.crypto_venues import (
    CryptoVenueProviderError,
    load_crypto_venue_bindings,
)

SCHEMA_VERSION = "capital-intelligence-certified-investable-catalog.v1"
DEFAULT_PATH = Path("database/certified-investable-catalog.json")
DEFAULT_CRYPTO_VENUE_BINDINGS_PATH = Path(
    "config/crypto_venue_bindings.all_markets.json"
)
CERTIFIED_CATALOG_ENV = "CAPITAL_INTELLIGENCE_CERTIFIED_INVESTABLE_CATALOG"
CRYPTO_VENUE_BINDINGS_ENV = "CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS"


class CertifiedInvestableCatalogError(RuntimeError):
    """Raised when a configured complete catalog cannot be certified."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CertifiedInvestableCatalogError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise CertifiedInvestableCatalogError(
            f"{field_name} must be ISO-8601"
        ) from error
    return _aware(parsed, field_name=field_name)


def configured_path() -> Path | None:
    value = os.getenv(CERTIFIED_CATALOG_ENV, "").strip()
    return None if not value else Path(value).expanduser()


def configured_crypto_venue_bindings_path() -> Path:
    value = os.getenv(CRYPTO_VENUE_BINDINGS_ENV, "").strip()
    return (
        DEFAULT_CRYPTO_VENUE_BINDINGS_PATH
        if not value
        else Path(value).expanduser()
    )


def _crypto_symbol(product_id: str, *, quote_currency: str) -> tuple[str, str]:
    parts = tuple(item.strip().upper() for item in product_id.split("-") if item.strip())
    if len(parts) != 2 or parts[1] != quote_currency:
        raise CertifiedInvestableCatalogError(
            "crypto venue binding must use a BASE-QUOTE Coinbase product matching "
            "its quote_currency"
        )
    return "".join(parts), parts[0]


def _certified_crypto_records() -> tuple[Mapping[str, object], ...]:
    source = configured_crypto_venue_bindings_path()
    try:
        registry = load_crypto_venue_bindings(source)
    except (CryptoVenueProviderError, OSError, TypeError, ValueError) as error:
        raise CertifiedInvestableCatalogError(
            f"certified multi-venue crypto catalog is unavailable at {source}: "
            f"{type(error).__name__}: {error}"
        ) from error
    if not registry.bindings:
        raise CertifiedInvestableCatalogError(
            "certified multi-venue crypto catalog cannot be empty"
        )

    records: list[Mapping[str, object]] = []
    for binding in registry.bindings:
        quote_currency = binding.quote_currency.upper()
        symbol, base_currency = _crypto_symbol(
            binding.coinbase_product_id,
            quote_currency=quote_currency,
        )
        kraken_symbol = binding.kraken_symbol.strip().upper()
        if "/" not in kraken_symbol:
            raise CertifiedInvestableCatalogError(
                f"crypto venue binding {binding.instrument_id!r} lacks a Kraken pair"
            )
        records.append(
            {
                "symbol": symbol,
                "provider_symbol": binding.coinbase_product_id,
                "name": f"{base_currency} / {quote_currency} spot crypto",
                "asset_class": "CRYPTO",
                "economic_exposure": "crypto",
                "venue": "COINBASE_KRAKEN",
                "country_code": "GLOBAL",
                "currency": quote_currency,
                "settlement_currency": quote_currency,
                "instrument_type": "spot",
                # Yahoo supplies governed long-horizon bars; independent Coinbase and
                # Kraken adapters remain mandatory for live quote validation.
                "provider_kind": "yahoo",
                "source_identifier": (
                    "multi-venue-crypto-binding:"
                    f"coinbase={binding.coinbase_product_id}:"
                    f"kraken={binding.kraken_symbol}"
                ),
                "instrument_identifier": binding.instrument_id,
                "contract_multiplier": 1.0,
                "quote_spread_bps": 30.0,
            }
        )
    return tuple(records)


def _external_catalog_records(
    *,
    timestamp: datetime,
    source: Path | None,
) -> tuple[Mapping[str, object], ...]:
    if source is None:
        return ()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise CertifiedInvestableCatalogError(
            f"configured certified catalog is unavailable at {source}"
        ) from error
    except json.JSONDecodeError as error:
        raise CertifiedInvestableCatalogError(
            "configured certified catalog is invalid JSON"
        ) from error
    if not isinstance(payload, Mapping):
        raise CertifiedInvestableCatalogError(
            "certified catalog must be a JSON object"
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CertifiedInvestableCatalogError(
            "unsupported certified catalog schema"
        )
    if payload.get("complete") is not True:
        raise CertifiedInvestableCatalogError(
            "certified catalog does not attest complete provider coverage"
        )
    catalog_as_of = _timestamp(payload.get("as_of"), field_name="as_of")
    available_at = _timestamp(
        payload.get("available_at"), field_name="available_at"
    )
    if catalog_as_of > timestamp or available_at > timestamp:
        raise CertifiedInvestableCatalogError(
            "certified catalog contains future-known membership"
        )
    raw_records = payload.get("records")
    if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
        raise CertifiedInvestableCatalogError("catalog records must be a sequence")
    records = tuple(item for item in raw_records if isinstance(item, Mapping))
    if len(records) != len(raw_records):
        raise CertifiedInvestableCatalogError(
            "every certified catalog record must be an object"
        )
    return records


def _validate_unique_identities(
    records: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    identities: set[str] = set()
    normalized = tuple(records)
    for index, record in enumerate(normalized):
        identifier = str(
            record.get("instrument_identifier")
            or record.get("source_identifier")
            or ""
        ).strip()
        if not identifier:
            raise CertifiedInvestableCatalogError(
                f"records[{index}] lacks a stable instrument/source identifier"
            )
        if identifier in identities:
            raise CertifiedInvestableCatalogError(
                f"duplicate certified instrument identity: {identifier}"
            )
        identities.add(identifier)
    return normalized


def load_certified_investable_catalog(
    *,
    as_of: datetime,
    path: str | Path | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Return capability-bound and externally published point-in-time records.

    The repository's multi-venue crypto registry is always required because direct
    crypto is a scheduled canonical discovery lane.  An optional external publication
    may add other fully certified instruments. Once its path is configured, absence,
    staleness, incompleteness, or malformed records fail closed instead of silently
    reverting to a smaller market universe.
    """

    timestamp = _aware(as_of, field_name="as_of")
    source = Path(path).expanduser() if path is not None else configured_path()
    records = (
        *_certified_crypto_records(),
        *_external_catalog_records(timestamp=timestamp, source=source),
    )
    return _validate_unique_identities(records)


__all__ = [
    "CERTIFIED_CATALOG_ENV",
    "CRYPTO_VENUE_BINDINGS_ENV",
    "CertifiedInvestableCatalogError",
    "DEFAULT_CRYPTO_VENUE_BINDINGS_PATH",
    "DEFAULT_PATH",
    "SCHEMA_VERSION",
    "configured_crypto_venue_bindings_path",
    "configured_path",
    "load_certified_investable_catalog",
]
