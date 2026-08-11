"""Provider credential alias normalization shared by runtime and governance code.

The platform has accumulated provider integrations over time and some adapters/config
files use different environment-variable spellings for the same credential. Each entry
below is an equivalence group: if any name is configured, every missing name in that
group is populated process-locally with the same value. Secret values are never logged,
serialized, or written back to GitHub/Render by this module.
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
    "ALPACA_MARKET_DATA_API_SECRET": (
        "CAPITAL_INTELLIGENCE_ALPACA_MARKET_DATA_API_SECRET",
        "ALPACA_DATA_API_SECRET",
        "ALPACA_API_SECRET",
        "ALPACA_SECRET_KEY",
        "APCA_API_SECRET_KEY",
    ),
    "DATABENTO_API_KEY": (
        "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
        "DATABENTO_KEY",
        "DATABENTO_API_TOKEN",
        "DBN_API_KEY",
    ),
    "EODHD_API_KEY": (
        "CAPITAL_INTELLIGENCE_EODHD_API_KEY",
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
        "EODHD_API_TOKEN",
        "EODHD_KEY",
    ),
    "MASSIVE_API_KEY": (
        "CAPITAL_INTELLIGENCE_MASSIVE_API_KEY",
        "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY",
        "POLYGON_API_KEY",
    ),
    "TWELVE_DATA_API_KEY": (
        "TWELVE_API_KEY",
        "CAPITAL_INTELLIGENCE_TWELVE_DATA_API_KEY",
        "TWELVEDATA_API_KEY",
    ),
    "ALPHA_VANTAGE_API_KEY": (
        "ALPHAVANTAGE_API_KEY",
        "CAPITAL_INTELLIGENCE_ALPHA_VANTAGE_API_KEY",
        "ALPHA_VANTAGE_KEY",
    ),
    "OPENFIGI_API_KEY": (
        "OPEN_FIGI_API_KEY",
        "CAPITAL_INTELLIGENCE_OPENFIGI_API_KEY",
        "OPENFIGI_KEY",
        "OPENFIGI_TOKEN",
    ),
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
    "FINRA_CLIENT_ID": ("CAPITAL_INTELLIGENCE_FINRA_CLIENT_ID",),
    "FINRA_CLIENT_SECRET": ("CAPITAL_INTELLIGENCE_FINRA_CLIENT_SECRET",),
    "FINRA_API_TOKEN": ("CAPITAL_INTELLIGENCE_FINRA_API_TOKEN",),
    "CAPITAL_INTELLIGENCE_LSEG_MARKET_DATA_API_KEY": ("LSEG_MARKET_DATA_API_KEY",),
    "CAPITAL_INTELLIGENCE_LSEG_REFERENCE_API_KEY": ("LSEG_REFERENCE_API_KEY",),
    "CAPITAL_INTELLIGENCE_LSEG_FUNDAMENTALS_API_KEY": ("LSEG_FUNDAMENTALS_API_KEY",),
    "CAPITAL_INTELLIGENCE_ICE_FIXED_INCOME_API_KEY": ("ICE_FIXED_INCOME_API_KEY",),
    "CAPITAL_INTELLIGENCE_ICE_MARGIN_API_KEY": ("ICE_MARGIN_API_KEY",),
    "SEC_USER_AGENT": ("CAPITAL_INTELLIGENCE_SEC_USER_AGENT",),
}


def _group_value(
    source: Mapping[str, str],
    canonical: str,
    aliases: tuple[str, ...],
) -> str | None:
    for name in (canonical, *aliases):
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_provider_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a copy with every supported name populated within each alias group."""

    result = dict(os.environ if environment is None else environment)
    for canonical, aliases in PROVIDER_ENVIRONMENT_ALIASES.items():
        value = _group_value(result, canonical, aliases)
        if value is None:
            continue
        for name in (canonical, *aliases):
            current = result.get(name)
            if not isinstance(current, str) or not current.strip():
                result[name] = value
    return result


def install_provider_environment_aliases(
    environment: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Populate missing supported aliases in one process-local environment."""

    target = os.environ if environment is None else environment
    normalized = normalize_provider_environment(target)
    installed: list[str] = []
    for canonical, aliases in PROVIDER_ENVIRONMENT_ALIASES.items():
        for name in (canonical, *aliases):
            current = target.get(name)
            if isinstance(current, str) and current.strip():
                continue
            value = normalized.get(name)
            if isinstance(value, str) and value.strip():
                target[name] = value
                installed.append(name)
    return tuple(installed)


def provider_environment_value(
    canonical: str,
    *aliases: str,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Return the first non-empty canonical value or supported alias."""

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