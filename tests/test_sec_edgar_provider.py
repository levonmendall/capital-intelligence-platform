"""Offline contract tests for the official SEC EDGAR adapter."""

from datetime import datetime, timezone

import pytest
import requests

from data import (
    FilingProvider,
    FilingQuery,
    SecurityMasterError,
    SecurityMasterIngestionQuery,
)
from providers.sec_edgar import (
    SEC_COMPANY_FACTS_URL,
    SEC_SUBMISSIONS_URL,
    SEC_TICKERS_URL,
    SECEdgarProvider,
    SECEdgarProviderError,
)


CIK = "0000320193"
RETRIEVED_AT = datetime(
    2025,
    2,
    12,
    18,
    0,
    tzinfo=timezone.utc,
)


class FakeResponse:
    """Minimal requests-compatible JSON response."""

    def __init__(
        self,
        payload: object,
        error: requests.RequestException | None = None,
    ) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> object:
        return self._payload


def submissions_payload() -> dict[str, object]:
    """Return aligned SEC recent-filing columns."""

    return {
        "cik": CIK,
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-25-000010",
                    "0000320193-25-000009",
                    "0000320193-25-000008",
                ],
                "filingDate": [
                    "2025-02-11",
                    "2025-02-03",
                    "2025-01-31",
                ],
                "reportDate": [
                    "2025-02-10",
                    "2024-12-28",
                    "2024-12-28",
                ],
                "acceptanceDateTime": [
                    "2025-02-11T09:00:00-05:00",
                    "2025-02-03T17:01:02",
                    "2025-01-31T16:30:00-05:00",
                ],
                "form": ["8-K", "10-Q/A", "10-Q"],
                "primaryDocument": [
                    "event.htm",
                    "amendment.htm",
                    "quarter.htm",
                ],
            }
        },
    }


def company_facts_payload() -> dict[str, object]:
    """Return facts including an amendment and future filing."""

    return {
        "cik": CIK,
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-09-29",
                                "end": "2024-12-28",
                                "val": 100,
                                "accn": "0000320193-25-000008",
                                "fy": 2025,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2025-01-31",
                                "frame": "CY2024Q4",
                            },
                            {
                                "start": "2024-09-29",
                                "end": "2024-12-28",
                                "val": 101,
                                "accn": "0000320193-25-000009",
                                "fy": 2025,
                                "fp": "Q1",
                                "form": "10-Q/A",
                                "filed": "2025-02-03",
                                "frame": "CY2024Q4",
                            },
                            {
                                "end": "2025-02-10",
                                "val": 999,
                                "accn": "0000320193-25-000010",
                                "form": "8-K",
                                "filed": "2025-02-11",
                            },
                        ]
                    }
                }
            }
        },
    }


def provider_for(
    payloads: dict[str, object],
) -> tuple[SECEdgarProvider, list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def http_get(
        url: str,
        **kwargs: object,
    ) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(payloads[url])

    provider = SECEdgarProvider(
        user_agent="Capital Intelligence test@example.com",
        clock=lambda: RETRIEVED_AT,
        http_get=http_get,
    )
    return provider, calls


def test_provider_satisfies_filing_protocol() -> None:
    provider, _ = provider_for({})

    assert isinstance(provider, FilingProvider)
    assert provider.name == "SEC_EDGAR"
    assert provider.configured


def test_security_master_uses_required_identity_header() -> None:
    provider, calls = provider_for(
        {
            SEC_TICKERS_URL: {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                    [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
                ],
            }
        }
    )

    snapshot = provider.fetch_security_master()

    instrument = snapshot.resolve_symbol("AAPL", venue="Nasdaq")
    assert instrument.issuer_id == f"SEC:CIK:{CIK}"
    assert instrument.identifiers[0].value == "AAPL"
    assert snapshot.observed_at == RETRIEVED_AT
    assert calls[0]["headers"] == {
        "User-Agent": "Capital Intelligence test@example.com",
        "Accept-Encoding": "gzip, deflate",
    }


def test_security_master_delivery_discloses_current_only_coverage() -> None:
    provider, _ = provider_for(
        {
            SEC_TICKERS_URL: {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
            }
        }
    )
    query = SecurityMasterIngestionQuery(
        identifier="sec-test",
        as_of=RETRIEVED_AT,
        knowledge_cutoff=RETRIEVED_AT,
        requested_at=RETRIEVED_AT,
    )

    delivery = provider.fetch_security_master_delivery(query)

    assert delivery.request_identifier == "sec-test"
    assert delivery.observed_at == RETRIEVED_AT
    assert delivery.retrieved_at == RETRIEVED_AT
    assert delivery.catalog.coverage.source == "SEC_EDGAR"
    assert delivery.catalog.coverage.authoritative is False
    assert "delisted securities" in delivery.catalog.coverage.deficiencies


def test_filings_use_acceptance_timestamp_as_boundary() -> None:
    url = SEC_SUBMISSIONS_URL.format(cik=CIK)
    provider, _ = provider_for({url: submissions_payload()})
    query = FilingQuery(
        cik=CIK,
        as_of=datetime(
            2025,
            2,
            3,
            22,
            0,
            tzinfo=timezone.utc,
        ),
        forms=("10-Q", "10-Q/A"),
    )

    filings = provider.fetch_filings(query)

    assert [filing.form for filing in filings] == ["10-Q"]
    assert filings[0].accepted_at == datetime(
        2025,
        1,
        31,
        21,
        30,
        tzinfo=timezone.utc,
    )
    assert filings[0].source_url.endswith(
        "/320193/000032019325000008/quarter.htm"
    )


def test_company_facts_preserve_original_and_amended_values() -> None:
    submissions_url = SEC_SUBMISSIONS_URL.format(cik=CIK)
    facts_url = SEC_COMPANY_FACTS_URL.format(cik=CIK)
    provider, _ = provider_for(
        {
            submissions_url: submissions_payload(),
            facts_url: company_facts_payload(),
        }
    )
    query = FilingQuery(
        cik=CIK,
        as_of=datetime(
            2025,
            2,
            10,
            tzinfo=timezone.utc,
        ),
        forms=("10-Q", "10-Q/A"),
    )

    facts = provider.fetch_company_facts(query)

    assert [fact.value for fact in facts] == [101.0, 100.0]
    assert facts[0].is_amendment
    assert not facts[1].is_amendment
    assert all(fact.accepted_at <= query.as_of for fact in facts)


def test_fact_without_acceptance_record_is_not_available() -> None:
    submissions_url = SEC_SUBMISSIONS_URL.format(cik=CIK)
    facts_url = SEC_COMPANY_FACTS_URL.format(cik=CIK)
    payload = company_facts_payload()
    units = payload["facts"]["us-gaap"][  # type: ignore[index]
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]["units"]["USD"]  # type: ignore[index]
    units.append(
        {
            "end": "2024-12-28",
            "val": 777,
            "accn": "unknown-accession",
            "form": "10-Q",
            "filed": "2025-01-01",
        }
    )
    provider, _ = provider_for(
        {
            submissions_url: submissions_payload(),
            facts_url: payload,
        }
    )

    facts = provider.fetch_company_facts(
        FilingQuery(
            cik=CIK,
            as_of=RETRIEVED_AT,
            forms=("10-Q", "10-Q/A"),
        )
    )

    assert all(
        fact.accession_number != "unknown-accession"
        for fact in facts
    )


def test_provider_requires_sec_user_agent() -> None:
    provider = SECEdgarProvider(
        user_agent=None,
        clock=lambda: RETRIEVED_AT,
        http_get=lambda *_args, **_kwargs: FakeResponse({}),
    )
    provider.user_agent = None

    with pytest.raises(SECEdgarProviderError, match="SEC_USER_AGENT"):
        provider.fetch_security_master()


def test_provider_wraps_network_failures() -> None:
    def failing_get(
        _url: str,
        **_kwargs: object,
    ) -> FakeResponse:
        return FakeResponse(
            {},
            requests.ConnectionError("offline"),
        )

    provider = SECEdgarProvider(
        user_agent="Capital Intelligence test@example.com",
        clock=lambda: RETRIEVED_AT,
        http_get=failing_get,
    )

    with pytest.raises(SECEdgarProviderError, match="request failed"):
        provider.fetch_security_master()


def test_sec_security_master_catalog_is_explicitly_current_only() -> None:
    provider, _ = provider_for(
        {
            SEC_TICKERS_URL: {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
            }
        }
    )

    catalog = provider.fetch_security_master_catalog()

    assert catalog.coverage.authoritative is False
    assert "historical identifiers" in catalog.coverage.deficiencies
    snapshot = catalog.snapshot(as_of=RETRIEVED_AT)
    assert snapshot.resolve_symbol("AAPL", venue="NASDAQ").name == "Apple Inc."
    with pytest.raises(SecurityMasterError, match="not authoritative"):
        catalog.snapshot(as_of=RETRIEVED_AT, require_authoritative=True)
