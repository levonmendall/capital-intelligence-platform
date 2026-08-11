"""Provider credential alias normalization shared by runtime and governance code.

The platform has accumulated provider integrations over time and some adapters/config
files use different environment-variable spellings for the same credential.  Keep the
aliases here so every provider process sees the same credential without copying,
logging, or changing the underlying secret value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping


PROVIDER_ENVIRONMENT_ALIASES: dict[str, tuple[str, ...]] = {
    # Alpaca market-data credentials.  Execution remains paper-only and is governed
    # separately; these aliases only make existing market-data credentials reachable.
    "ALPACA_MARKET_DATA_API_KEY": (
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_KEY",
        "ALPACA_DATA_API_KEY",
        "ALPACA_API_KEY",
        "APCA_API_KEY_ID",
    ),
    "ALPACA_MARKET_DATA_API_SECRET": (
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_SECRET",
        "ALPACA_DATA_API_SECRET",
        "ALPACA_API_SECRET",
        "ALPACA_SECRET_KEY",
        "APCA_API_SECRET_KEY",
    ),
    "APCA_API_KEY_ID": (
        "ALPACA_MARKET_DATA_API_KEY",
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_KEY",
        "ALPACA_DATA_API_KEY",
        "ALPACA_API_KEY",
    ),
    "APCA_API_SECRET_KEY": (
        "ALPACA_MARKET_DATA_API_SECRET",
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_SECRET",
        "ALPACA_DATA_API_SECRET",
        "ALPACA_API_SECRET",
        "ALPACA_SECRET_KEY",
    ),
    # Databento.
    "DATABENTO_API_KEY": (
        "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
        "DATABENTO_KEY",
        "DATABENTO_API_TOKEN",
        "DBN_API_KEY",
    ),
    "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY": (
        "DATABENTO_API_KEY",
        "DATABENTO_KEY",
        "DATABENTO_API_TOKEN",
        "DBN_API_KEY",
    ),
    # EODHD.
    "EODHD_API_KEY": (
        "CAPITAL_INTELLIGENCE_EODHD_API_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
        "EODHD_API_TOKEN",
        "EODHD_KEY",
    ),
    "EODHD_API_TOKEN": (
        "EODHD_API_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
        "EODHD_KEY",
    ),
    "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN": (
        "EODHD_API_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_KEY",
        "EODHD_API_TOKEN",
        "EODHD_KEY",
    ),
    # Massive (formerly Polygon-compatible naming is retained for existing secrets).
    "MASSIVE_API_KEY": (
        "CAPITAL_INTELLIGENCE_MASSIVE_API_KEY",
        "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY",
        "POLYGON_API_KEY",
    ),
    "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY": (
        "MASSIVE_API_KEY",
        "CAPITAL_INTELLIGENCE_MASSIVE_API_KEY",
        "POLYGON_API_KEY",
    ),
    # Twelve Data.
    "TWELVE_DATA_API_KEY": (
        "TWELVE_API_KEY",
        "CAPITAL_INTELLIGENCE_TWELVE_DATA_API_KEY",
        "TWELVEDATA_API_KEY",
    ),
    "TWELVE_API_KEY": (
        "TWELVE_DATA_API_KEY",
        "CAPITAL_INTELLIGENCE_TWELVE_DATA_API_KEY",
        "TWELVEDATA_API_KEY",
    ),
    # Alpha Vantage.
    "ALPHAVANTAGE_API_KEY": (
        "ALPHA_VANTAGE_API_KEY",
        "CAPITAL_INTELLIGENCE_ALPHA_VANTAGE_API_KEY",
        "ALPHA_VANTAGE_KEY",
    ),
    "ALPHA_VANTAGE_API_KEY": (
        "ALPHAVANTAGE_API_KEY",
        "CAPITAL_INTELLIGENCE_ALPHA_VANTAGE_API_KEY",
        "ALPHA_VANTAGE_KEY",
    ),
    # OpenFIGI.
    "OPENFIGI_API_KEY": (
        "OPEN_FIGI_API_KEY",
        "CAPITAL_INTELLIGENCE_OPENFIGI_API_KEY",
        "OPENFIGI_KEY",
        "OPENFIGI_TOKEN",
    ),
    # Public/economic APIs used by governed information collection.
    "FRED_API_KEY": ("CAPITAL_INTELLIGENCE_FRED_API_KEY", "FRED_KEY"),
    "BEA_API_KEY": ("CAPITAL_INTELLIGENCE_BEA_API_KEY", "BEA_KEY"),
    "CENSUS_API_KEY": ("CAPITAL_INTELLIGENCE_CENSUS_API_KEY", "CENSUS_KEY"),
    "EIA_API_KEY": ("CAPITAL_INTELLIGENCE_EIA_API_KEY", "EIA_KEY"),
    "USDA_NASS_API_KEY": (
        "CAPITAL_INTELLIGENCE_USDA_NASS_API_KEY",
        "NASS_API_KEY",
        "USDA_API_KEY",
    ),
    "NASA_FIRMS_MAP_KEY": (
        "CAPITAL_INTELLIGENCE_NASA_FIRMS_MAP_KEY",
        "NASA_FIRMS_API_KEY",
        "FIRMS_MAP_KEY",
    ),
    # FINRA integrations may use authenticated Data/API Platform access.  These
    # aliases intentionally do not imply that authentication is required for every
    # public TRACE dataset.
    "FINRA_CLIENT_ID": ("CAPITAL_INTELLIGENCE_FINRA_CLIENT_ID",),
    "FINRA_CLIENT_SECRET": ("CAPITAL_INTELLIGENCE_FINRA_CLIENT_SECRET",),
    "FINRA_API_TOKEN": ("CAPITAL_INTELLIGENCE_FINRA_API_TOKEN",),
    # Identity string used by SEC endpoints; not a secret, but normalize it with the
    # rest of provider environment so standalone workers receive the same value.
    "SEC_USER_AGENT": ("CAPITAL_INTELLIGENCE_SEC_USER_AGENT",),
}


def normalize_provider_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a copy with canonical provider variables populated from aliases."""

    result = dict(os.environ if environment is None else environment)
    for canonical, aliases in PROVIDER_ENVIRONMENT_ALIASES.items():
        current = result.get(canonical)
        if isinstance(current, str) and current.strip():
            continue
        for alias in aliases:
            value = result.get(alias)
            if isinstance(value, str) and value.strip():
                result[canonical] = value.strip()
                break
    return result


def install_provider_environment_aliases(
    environment: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Populate missing canonical variables in one process-local environment."""

    target = os.environ if environment is None else environment
    normalized = normalize_provider_environment(target)
    installed: list[str] = []
    for canonical in PROVIDER_ENVIRONMENT_ALIASES:
        current = target.get(canonical)
        if isinstance(current, str) and current.strip():
            continue
        value = normalized.get(canonical)
        if isinstance(value, str) and value.strip():
            target[canonical] = value
            installed.append(canonical)
    return tuple(installed)


def provider_environment_value(
    canonical: str,
    *aliases: str,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Return the first non-empty canonical value or configured alias from a mapping."""

    source = os.environ if environment is None else environment
    names: list[str] = [canonical]
    names.extend(PROVIDER_ENVIRONMENT_ALIASES.get(canonical, ()))
    names.extend(aliases)
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


__all__ = [
    "PROVIDER_ENVIRONMENT_ALIASES",
    "install_provider_environment_aliases",
    "normalize_provider_environment",
    "provider_environment_value",
]