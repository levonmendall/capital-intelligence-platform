"""Instrument-level availability handling for SEC Company Facts.

The SEC Company Facts endpoint is not published for every SEC filer. A 404 for one
issuer is therefore an instrument-level absence, not proof that SEC evidence is
unavailable for the entire governed universe. All other SEC failures remain fail-closed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from data import CompanyFact, FilingQuery
from providers.sec_edgar import SECEdgarProviderError
from providers.sec_edgar_resilient import ResilientSECEdgarProvider


_LOGGER = logging.getLogger("capital_intelligence.providers.sec_edgar")
_AVAILABILITY_POLICY_VERSION = "sec-company-facts-availability.v1"
_INSTALL_MARKER = "_company_facts_availability_policy_version"
_ORIGINAL_MARKER = "_company_facts_availability_original"


def _http_status_code(error: BaseException) -> int | None:
    """Return the first HTTP response status preserved in an exception chain."""

    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        response = getattr(current, "response", None)
        raw_status = getattr(response, "status_code", None)
        if isinstance(raw_status, int):
            return raw_status
        next_error = getattr(current, "__cause__", None)
        if next_error is None:
            next_error = getattr(current, "__context__", None)
        current = next_error if isinstance(next_error, BaseException) else None
    return None


def install_company_facts_availability_boundary() -> type[ResilientSECEdgarProvider]:
    """Install one idempotent production boundary on the compatibility provider.

    Keeping the existing class identity preserves the repository's historical provider
    injection and monkeypatch contracts while changing only the production handling of
    a missing Company Facts resource.
    """

    provider_type = ResilientSECEdgarProvider
    if getattr(provider_type, _INSTALL_MARKER, None) == _AVAILABILITY_POLICY_VERSION:
        return provider_type

    original = provider_type.fetch_company_facts

    def fetch_company_facts(
        self: ResilientSECEdgarProvider,
        query: FilingQuery,
    ) -> tuple[CompanyFact, ...]:
        try:
            return original(self, query)
        except SECEdgarProviderError as error:
            status_code = _http_status_code(error)
            if status_code != 404:
                raise
            _LOGGER.warning(
                "SEC company facts unavailable for issuer",
                extra={
                    "cik": query.cik,
                    "status_code": status_code,
                    "policy_version": _AVAILABILITY_POLICY_VERSION,
                    "candidate_authority": False,
                    "sizing_authority": False,
                    "execution_authority": False,
                    "real_money_authorized": False,
                },
            )
            return ()

    fetch_company_facts.__name__ = original.__name__
    fetch_company_facts.__qualname__ = original.__qualname__
    fetch_company_facts.__doc__ = (
        "Return governed company facts, or an empty instrument-level result when the "
        "SEC Company Facts resource is absent with HTTP 404."
    )
    setattr(provider_type, _ORIGINAL_MARKER, original)
    setattr(provider_type, "fetch_company_facts", fetch_company_facts)
    setattr(provider_type, _INSTALL_MARKER, _AVAILABILITY_POLICY_VERSION)
    return provider_type


__all__ = [
    "install_company_facts_availability_boundary",
]
