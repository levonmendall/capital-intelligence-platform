"""Regression coverage for instrument-level SEC Company Facts absence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

import production_paper_evidence as paper_evidence
from data import FilingQuery
from providers.sec_edgar import (
    SEC_COMPANY_FACTS_URL,
    SEC_SUBMISSIONS_URL,
    SECEdgarProviderError,
)
from providers.sec_edgar_resilient import ResilientSECEdgarProvider


AS_OF = datetime(2026, 8, 3, 18, 30, tzinfo=timezone.utc)
QQQ_CIK = "0001067839"


class _Response:
    def __init__(self, *, url: str, status_code: int, payload: object) -> None:
        self.url = url
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error",
                response=self,  # type: ignore[arg-type]
            )

    def json(self) -> object:
        return self._payload


def _query(cik: str = QQQ_CIK) -> FilingQuery:
    return FilingQuery(
        cik=cik,
        as_of=AS_OF,
        forms=("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"),
        limit=10_000,
    )


def test_company_facts_404_is_an_empty_instrument_level_result() -> None:
    calls: list[str] = []

    def http_get(url: str, **_kwargs: object) -> _Response:
        calls.append(url)
        return _Response(url=url, status_code=404, payload={})

    provider = ResilientSECEdgarProvider(
        user_agent="Capital Intelligence test@example.com",
        clock=lambda: AS_OF,
        http_get=http_get,
    )

    assert provider.fetch_company_facts(_query()) == ()
    assert calls == [SEC_COMPANY_FACTS_URL.format(cik=QQQ_CIK)]
    assert (
        getattr(
            ResilientSECEdgarProvider,
            "_company_facts_availability_policy_version",
        )
        == "sec-company-facts-availability.v1"
    )


def test_company_facts_500_remains_provider_wide_failure() -> None:
    def http_get(url: str, **_kwargs: object) -> _Response:
        return _Response(url=url, status_code=500, payload={})

    provider = ResilientSECEdgarProvider(
        user_agent="Capital Intelligence test@example.com",
        clock=lambda: AS_OF,
        http_get=http_get,
    )

    with pytest.raises(SECEdgarProviderError, match="company facts"):
        provider.fetch_company_facts(_query())


def test_submissions_404_remains_blocking() -> None:
    def http_get(url: str, **_kwargs: object) -> _Response:
        assert url == SEC_SUBMISSIONS_URL.format(cik=QQQ_CIK)
        return _Response(url=url, status_code=404, payload={})

    provider = ResilientSECEdgarProvider(
        user_agent="Capital Intelligence test@example.com",
        clock=lambda: AS_OF,
        http_get=http_get,
    )

    with pytest.raises(SECEdgarProviderError, match="submissions"):
        provider.fetch_filings(_query())


def test_production_binding_preserves_existing_provider_identity() -> None:
    paper_evidence._synchronize_runtime_bindings()

    assert paper_evidence.SECEdgarProvider is ResilientSECEdgarProvider
    assert paper_evidence._implementation.SECEdgarProvider is ResilientSECEdgarProvider
