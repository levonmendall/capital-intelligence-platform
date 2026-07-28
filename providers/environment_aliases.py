"""Compatibility exports for shared provider credential alias normalization."""

from provider_environment import (
    PROVIDER_ENVIRONMENT_ALIASES,
    install_provider_environment_aliases,
    normalize_provider_environment,
    provider_environment_value,
)

__all__ = [
    "PROVIDER_ENVIRONMENT_ALIASES",
    "install_provider_environment_aliases",
    "normalize_provider_environment",
    "provider_environment_value",
]
