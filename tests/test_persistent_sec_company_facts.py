from __future__ import annotations

from datetime import date, datetime, timezone

from data import CompanyFact, FilingQuery
from providers.persistent_sec_company_facts import PersistentSECCompanyFactsProvider


class _FakeSEC:
    def __init__(self, fact) -> None:
        self.fact = fact
        self.calls = 0

    def fetch_company_facts(self, query):
        self.calls += 1
        return (self.fact,)


def test_recent_company_facts_are_reused_without_sec_redownload(tmp_path) -> None:
    as_of = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)
    fact = CompanyFact(
        cik="0000320193",
        taxonomy="us-gaap",
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        unit="USD",
        value=100.0,
        period_start=date(2025, 10, 1),
        period_end=date(2025, 12, 31),
        filed_at=date(2026, 1, 30),
        accepted_at=datetime(2026, 1, 30, 21, 0, tzinfo=timezone.utc),
        retrieved_at=as_of,
        accession_number="0000320193-26-000001",
        form="10-K",
        fiscal_year=2025,
        fiscal_period="FY",
    )
    underlying = _FakeSEC(fact)
    provider = PersistentSECCompanyFactsProvider(
        underlying,
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
    )
    query = FilingQuery(
        cik="0000320193",
        as_of=as_of,
        forms=("10-K", "10-K/A"),
        limit=10_000,
    )

    first = provider.fetch_company_facts(query)
    second = provider.fetch_company_facts(query)

    assert first == (fact,)
    assert second == first
    assert underlying.calls == 1
