from __future__ import annotations

from datetime import datetime, timezone

import pytest

from providers.treasury_fiscal_data import (
    TreasuryFiscalDataError,
    TreasuryFiscalDataProvider,
)


class _Response:
    def __init__(self, payload, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_treasury_provider_returns_latest_active_point_in_time_cusips() -> None:
    calls = []

    def http_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(
            {
                "data": [
                    {
                        "record_date": "2026-08-10",
                        "cusip": "912797AB1",
                        "security_type": "Bill",
                        "security_term": "13-Week",
                        "auction_date": "2026-08-06",
                        "issue_date": "2026-08-11",
                        "maturity_date": "2026-11-10",
                        "high_discount_rate": "4.100",
                        "investment_rate": "4.250",
                        "price_per100": "98.970",
                        "bid_to_cover_ratio": "2.75",
                    },
                    {
                        "record_date": "2026-08-09",
                        "cusip": "912797AB1",
                        "security_type": "Bill",
                        "security_term": "13-Week",
                        "auction_date": "2026-08-06",
                        "issue_date": "2026-08-11",
                        "maturity_date": "2026-11-10",
                        "high_discount_rate": "4.000",
                    },
                    {
                        "record_date": "2026-08-10",
                        "cusip": "91282CZZ9",
                        "security_type": "Note",
                        "security_term": "2-Year",
                        "auction_date": "2026-07-27",
                        "issue_date": "2026-07-31",
                        "maturity_date": "2028-07-31",
                        "high_yield": "4.125",
                    },
                    {
                        "record_date": "2026-08-10",
                        "cusip": "91282CFU0",
                        "security_type": "Note",
                        "security_term": "2-Year",
                        "auction_date": "2026-08-20",
                        "issue_date": "2026-08-31",
                        "maturity_date": "2028-08-31",
                    },
                ],
                "meta": {"total-pages": 1},
            }
        )

    provider = TreasuryFiscalDataProvider(http_get=http_get)
    securities = provider.fetch_active_securities(
        as_of=datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc)
    )

    assert [item.cusip for item in securities] == ["912797AB1", "91282CZZ9"]
    bill = securities[0]
    assert bill.record_date.isoformat() == "2026-08-10"
    assert bill.investment_rate == 4.25
    assert bill.evidence_identifier == "treasury-fiscal-data:auctions_query:912797AB1:2026-08-10"
    assert calls
    params = calls[0][1]["params"]
    assert "record_date:lte:2026-08-11" in params["filter"]
    assert "issue_date:lte:2026-08-11" in params["filter"]
    assert "maturity_date:gte:2026-08-11" in params["filter"]


def test_treasury_provider_fails_closed_on_http_error() -> None:
    provider = TreasuryFiscalDataProvider(
        http_get=lambda *_args, **_kwargs: _Response({}, status_code=503)
    )

    with pytest.raises(TreasuryFiscalDataError, match="HTTP 503"):
        provider.fetch_active_securities(
            as_of=datetime(2026, 8, 11, tzinfo=timezone.utc)
        )


def test_treasury_provider_fails_closed_when_no_active_security_exists() -> None:
    provider = TreasuryFiscalDataProvider(
        http_get=lambda *_args, **_kwargs: _Response({"data": [], "meta": {"total-pages": 1}})
    )

    with pytest.raises(TreasuryFiscalDataError, match="no active point-in-time securities"):
        provider.fetch_active_securities(
            as_of=datetime(2026, 8, 11, tzinfo=timezone.utc)
        )


def test_treasury_provider_requires_aware_point_in_time_cutoff() -> None:
    provider = TreasuryFiscalDataProvider(http_get=lambda *_args, **_kwargs: _Response({"data": []}))

    with pytest.raises(ValueError, match="timezone-aware"):
        provider.fetch_active_securities(as_of=datetime(2026, 8, 11))
