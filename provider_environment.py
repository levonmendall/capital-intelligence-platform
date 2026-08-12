"""Provider credential alias normalization shared by runtime and governance code.

Provider integrations have accumulated different environment-variable spellings over
time. Each mapping entry names one runtime/config canonical variable and the aliases
that may satisfy it. Normalization only populates missing canonical names; it never
rewrites source aliases, logs a credential value, or persists a secret.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping


PROVIDER_ENVIRONMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "ALPACA_MARKET_DATA_API_KEY": (
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_KEY",
        "ALPACA_DATA_API_KEY",
        "ALPACA_API_KEY",
        "APCA_API_KEY_ID",
    ),
    "APCA_API_KEY_ID": (
        "ALPACA_MARKET_DATA_API_KEY",
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_KEY",
        "ALPACA_DATA_API_KEY",
        "ALPACA_API_KEY",
    ),
    "ALPACA_MARKET_DATA_API_SECRET": (
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_SECRET",
        "ALPACA_DATA_API_SECRET",
        "ALPACA_API_SECRET",
        "ALPACA_SECRET_KEY",
        "APCA_API_SECRET_KEY",
    ),
    "APCA_API_SECRET_KEY": (
        "ALPACA_MARKET_DATA_API_SECRET",
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_SECRET",
        "ALPACA_DATA_API_SECRET",
        "ALPACA_API_SECRET",
        "ALPACA_SECRET_KEY",
    ),
    "DATABENTO_API_KEY": (
        "DATABENTO_API_TOKEN",
        "DATABENTO_KEY",
        "DBN_API_KEY",
        "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
    ),
    "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY": ("DATABENTO_API_KEY",),
    "EODHD_API_KEY": (
        "EODHD_API_TOKEN",
        "EODHD_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
    ),
    "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN": (
        "EODHD_API_KEY",
        "EODHD_API_TOKEN",
        "EODHD_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_KEY",
    ),
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
    "TRADIER_API_KEY": (
        "TRADIER_API_TOKEN",
        "TRADIER_ACCESS_TOKEN",
        "TRADIER_TOKEN",
        "CAPITAL_INTELLIGENCE_TRADIER_API_KEY",
        "CAPITAL_INTELLIGENCE_TRADIER_API_TOKEN",
    ),
    "TRADIER_API_TOKEN": (
        "TRADIER_API_KEY",
        "TRADIER_ACCESS_TOKEN",
        "TRADIER_TOKEN",
        "CAPITAL_INTELLIGENCE_TRADIER_API_KEY",
        "CAPITAL_INTELLIGENCE_TRADIER_API_TOKEN",
    ),
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
    "ALPHA_VANTAGE_API_KEY": (
        "ALPHAVANTAGE_API_KEY",
        "CAPITAL_INTELLIGENCE_ALPHA_VANTAGE_API_KEY",
        "ALPHA_VANTAGE_KEY",
    ),
    "ALPHAVANTAGE_API_KEY": (
        "ALPHA_VANTAGE_API_KEY",
        "CAPITAL_INTELLIGENCE_ALPHA_VANTAGE_API_KEY",
        "ALPHA_VANTAGE_KEY",
    ),
    "OPEN_FIGI_API_KEY": (
        "CAPITAL_INTELLIGENCE_OPENFIGI_API_KEY",
        "OPENFIGI_KEY",
        "OPENFIGI_TOKEN",
    ),
    "OPENFIGI_API_KEY": ("OPEN_FIGI_API_KEY",),
    "FRED_API_KEY": ("CAPITAL_INTELLIGENCE_FRED_API_KEY", "FRED_KEY"),
    "BEA_API_KEY": ("CAPITAL_INTELLIGENCE_BEA_API_KEY", "BEA_KEY"),
    "CENSUS_API_KEY": (
        "CAPITAL_INTELLIGENCE_CENSUS_API_KEY",
        "US_CENSUS_API_KEY",
        "US_CENSUS_KEY",
        "CENSUS_KEY",
    ),
    "EIA_API_KEY": ("CAPITAL_INTELLIGENCE_EIA_API_KEY", "EIA_KEY"),
    "USDA_NASS_API_KEY": (
        "CAPITAL_INTELLIGENCE_USDA_NASS_API_KEY",
        "NASS_API_KEY",
        "USDA_API_KEY",
    ),
    "NASA_FIRMS_MAP_KEY": (
        "CAPITAL_INTELLIGENCE_NASA_FIRMS_MAP_KEY",
        "NASA_FIRMS_API_KEY",
        "NASA_API_KEY",
        "NASA_MAP_KEY",
        "FIRMS_MAP_KEY",
    ),
    # FINRA's credential is a client-ID/client-secret pair. The repository's
    # legacy FINRA_API_KEY name may hold the API Client ID, but it never becomes
    # a complete credential without a separately configured client secret.
    "FINRA_CLIENT_ID": (
        "CAPITAL_INTELLIGENCE_FINRA_CLIENT_ID",
        "FINRA_API_CLIENT_ID",
        "FINRA_API_KEY_ID",
        "FINRA_API_KEY",
    ),
    "FINRA_CLIENT_SECRET": (
        "CAPITAL_INTELLIGENCE_FINRA_CLIENT_SECRET",
        "FINRA_API_CLIENT_SECRET",
        "FINRA_API_SECRET",
        "FINRA_API_SECRET_KEY",
    ),
    "FINRA_API_TOKEN": (
        "CAPITAL_INTELLIGENCE_FINRA_API_TOKEN",
        "FINRA_ACCESS_TOKEN",
        "FINRA_BEARER_TOKEN",
    ),
    # CME DataMine uses an API ID/password pair for OAuth authentication.
    "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_ID": (
        "CME_DATAMINE_API_ID",
        "CME_API_ID",
    ),
    "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_PASSWORD": (
        "CME_DATAMINE_API_PASSWORD",
        "CME_API_PASSWORD",
    ),
    "CAPITAL_INTELLIGENCE_LSEG_MARKET_DATA_API_KEY": ("LSEG_MARKET_DATA_API_KEY",),
    "CAPITAL_INTELLIGENCE_LSEG_REFERENCE_API_KEY": ("LSEG_REFERENCE_API_KEY",),
    "CAPITAL_INTELLIGENCE_LSEG_FUNDAMENTALS_API_KEY": ("LSEG_FUNDAMENTALS_API_KEY",),
    "CAPITAL_INTELLIGENCE_ICE_FIXED_INCOME_API_KEY": ("ICE_FIXED_INCOME_API_KEY",),
    "CAPITAL_INTELLIGENCE_ICE_MARGIN_API_KEY": ("ICE_MARGIN_API_KEY",),
    "SEC_USER_AGENT": ("CAPITAL_INTELLIGENCE_SEC_USER_AGENT",),
}


def _first_value(source: Mapping[str, str], canonical: str, aliases: tuple[str, ...]) -> str | None:
    current = source.get(canonical)
    if isinstance(current, str) and current.strip():
        return current.strip()
    for name in aliases:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_provider_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    result = dict(os.environ if environment is None else environment)
    for canonical, aliases in PROVIDER_ENVIRONMENT_ALIASES.items():
        current = result.get(canonical)
        if isinstance(current, str) and current.strip():
            continue
        value = _first_value(result, canonical, aliases)
        if value is not None:
            result[canonical] = value
    return result


def install_provider_environment_aliases(environment: MutableMapping[str, str] | None = None) -> tuple[str, ...]:
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


def provider_environment_value(canonical: str, *aliases: str, environment: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if environment is None else environment
    configured_aliases = PROVIDER_ENVIRONMENT_ALIASES.get(canonical, ())
    seen: set[str] = set()
    for name in (canonical, *configured_aliases, *aliases):
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
