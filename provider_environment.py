"""Provider credential alias normalization shared by runtime and governance code."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping


PROVIDER_ENVIRONMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY": ("DATABENTO_API_KEY",),
    "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN": (
        "EODHD_API_KEY",
        "EODHD_API_TOKEN",
    ),
    "OPENFIGI_API_KEY": ("OPEN_FIGI_API_KEY",),
    "ALPHAVANTAGE_API_KEY": ("ALPHA_VANTAGE_API_KEY",),
    "TWELVE_API_KEY": ("TWELVE_DATA_API_KEY",),
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
    """Return the first non-empty canonical value or alias from a mapping."""

    source = os.environ if environment is None else environment
    for name in (canonical, *aliases):
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
