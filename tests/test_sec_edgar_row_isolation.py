"""Regression coverage for scope-aware malformed SEC filing rows."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import production_paper_evidence as paper_evidence
from data import FilingQuery
from providers.sec_edgar import (
    SEC_COMPANY_FACTS_URL,
    SEC_SUBMISSIONS_URL,
    SECEdgarProviderError,
)
from providers.sec_edgar_resilient import ResilientSECEdgarProvider


CIK = "0000320193"
RETRIEVED_AT = datetime(2026, 8, 3, 15, 30, tzinfo=timezone.utc)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def _payload(
    *,
    invalid_indexes: set[int],
    row_count: int = 3,
    forms: list[str] | None = None,
) -> dict[str, object]:
    acceptance = ["2026-07-31T16:30:00-04:00"] * row_count
    for index in invalid_indexes:
        acceptance[index] = "not-a-timestamp"
    return {
        "filings": {
            "recent": {
                "accessionNumber": [
                    f"0000320193-26-{index:06d}"
                    for index in range(row_count)
                ],
                "filingDate": ["2026-07-31"] * row_count,
                "reportDate": ["2026-06-30"] * row_count,
                "acceptanceDateTime": acceptance,
                "form": forms or ["10-K"] * row_count,
                "primaryDocument": [
                    f"filing-{index}.htm"
                    for index in range(row_count)
                ],
            }
        }
    }


def _facts_payload(
    accessions: tuple[str, ...],
    *,
    form: str,
) -> dict[str, object]:
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2026-01-01",
                                "end": "2026-06-30",
                                "val": 100 + index,
                                "accn": accession,
                                "fy": 2026,
                                "fp": "FY",
                                "form": form,
                                "filed": "2026-07-31",
                            }
                            for index, accession in enumerate(accessions)
                        ]
                    }
                }
            }
        }
    }


def _provider(
    *,
    cik: str,
    submissions: dict[str, object],
    facts: dict[str, object],
) -> ResilientSECEdgarProvider:
    payloads = {
        SEC_SUBMISSIONS_URL.format(cik=cik): submissions,
        SEC_COMPANY_FACTS_URL.format(cik=cik): facts,
    }

    def http_get(url: str, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(payloads[url])

    return ResilientSECEdgarProvider(
        user_agent="Capital Intelligence test@example.com",
        clock=lambda: RETRIEVED_AT,
        http_get=http_get,
    )


def test_one_malformed_historical_filing_does_not_discard_valid_rows() -> None:
    records = ResilientSECEdgarProvider._filing_records(
        _payload(invalid_indexes={1}),
        cik=CIK,
        retrieved_at=RETRIEVED_AT,
    )

    assert [record.accession_number for record in records] == [
        "0000320193-26-000000",
        "0000320193-26-000002",
    ]
    assert all(record.retrieved_at == RETRIEVED_AT for record in records)


def test_asml_sized_trailing_legacy_suffix_is_bounded_and_usable() -> None:
    records = ResilientSECEdgarProvider._filing_records(
        _payload(
            row_count=591,
            invalid_indexes=set(range(585, 591)),
        ),
        cik="0000937966",
        retrieved_at=RETRIEVED_AT,
    )

    assert len(records) == 585
    assert records[-1].accession_number == "0000320193-26-000584"


def test_suncor_sized_trailing_legacy_suffix_is_bounded_and_usable() -> None:
    records = ResilientSECEdgarProvider._filing_records(
        _payload(
            row_count=993,
            invalid_indexes=set(range(982, 993)),
        ),
        cik="0000311337",
        retrieved_at=RETRIEVED_AT,
    )

    assert len(records) == 982
    assert records[-1].accession_number == "0000320193-26-000981"


def test_qqq_legacy_fund_rows_do_not_block_corporate_form_query() -> None:
    forms = ["10-K"] * 242 + ["497"] * 12
    records = ResilientSECEdgarProvider._filing_records(
        _payload(
            row_count=254,
            invalid_indexes=set(range(242, 254)),
            forms=forms,
        ),
        cik="0001067839",
        retrieved_at=RETRIEVED_AT,
        forms=("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"),
    )

    assert len(records) == 242
    assert all(record.form == "10-K" for record in records)


def test_same_qqq_sized_corruption_in_requested_forms_remains_fail_closed() -> None:
    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid in-scope filing rows",
    ):
        ResilientSECEdgarProvider._filing_records(
            _payload(
                row_count=254,
                invalid_indexes=set(range(242, 254)),
            ),
            cik="0001067839",
            retrieved_at=RETRIEVED_AT,
            forms=("10-K",),
        )


def test_company_fact_collection_scopes_submissions_before_parsing() -> None:
    submissions = _payload(
        row_count=2,
        invalid_indexes={1},
        forms=["10-K", "497"],
    )
    facts = _facts_payload(
        ("0000320193-26-000000",),
        form="10-K",
    )
    provider = _provider(cik=CIK, submissions=submissions, facts=facts)

    result = provider.fetch_company_facts(
        FilingQuery(
            cik=CIK,
            as_of=RETRIEVED_AT,
            forms=("10-K",),
            limit=100,
        )
    )

    assert len(result) == 1
    assert result[0].accession_number == "0000320193-26-000000"
    assert result[0].form == "10-K"


def test_stm_pre_xbrl_annual_rows_do_not_block_company_facts() -> None:
    cik = "0000932787"
    row_count = 963
    forms = ["6-K"] * 931 + ["20-F"] * 32
    submissions = _payload(
        row_count=row_count,
        invalid_indexes={959, 960, 961, 962},
        forms=forms,
    )
    referenced_accession = "0000320193-26-000931"
    facts = _facts_payload((referenced_accession,), form="20-F")
    provider = _provider(cik=cik, submissions=submissions, facts=facts)

    result = provider.fetch_company_facts(
        FilingQuery(
            cik=cik,
            as_of=RETRIEVED_AT,
            forms=("20-F", "20-F/A"),
            limit=100,
        )
    )

    assert len(result) == 1
    assert result[0].accession_number == referenced_accession
    assert result[0].form == "20-F"


def test_stm_unreferenced_legacy_rows_remain_strict_for_filing_query() -> None:
    cik = "0000932787"
    forms = ["6-K"] * 931 + ["20-F"] * 32
    submissions = _payload(
        row_count=963,
        invalid_indexes={959, 960, 961, 962},
        forms=forms,
    )
    provider = _provider(cik=cik, submissions=submissions, facts={"facts": {}})

    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid in-scope filing rows",
    ):
        provider.fetch_filings(
            FilingQuery(
                cik=cik,
                as_of=RETRIEVED_AT,
                forms=("20-F", "20-F/A"),
                limit=100,
            )
        )


def test_excessive_malformed_fact_references_remain_fail_closed() -> None:
    cik = "0000932787"
    submissions = _payload(
        row_count=3,
        invalid_indexes={1, 2},
        forms=["20-F", "20-F", "20-F"],
    )
    facts = _facts_payload(
        (
            "0000320193-26-000000",
            "0000320193-26-000001",
            "0000320193-26-000002",
        ),
        form="20-F",
    )
    provider = _provider(cik=cik, submissions=submissions, facts=facts)

    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid in-scope filing rows",
    ):
        provider.fetch_company_facts(
            FilingQuery(
                cik=cik,
                as_of=RETRIEVED_AT,
                forms=("20-F",),
                limit=100,
            )
        )


def test_same_invalid_count_scattered_through_history_remains_fail_closed() -> None:
    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid in-scope filing rows",
    ):
        ResilientSECEdgarProvider._filing_records(
            _payload(
                row_count=993,
                invalid_indexes={
                    100,
                    200,
                    300,
                    400,
                    500,
                    600,
                    700,
                    800,
                    900,
                    950,
                    992,
                },
            ),
            cik="0000311337",
            retrieved_at=RETRIEVED_AT,
        )


def test_trailing_legacy_suffix_over_two_percent_remains_fail_closed() -> None:
    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid in-scope filing rows",
    ):
        ResilientSECEdgarProvider._filing_records(
            _payload(
                row_count=993,
                invalid_indexes=set(range(973, 993)),
            ),
            cik="0000311337",
            retrieved_at=RETRIEVED_AT,
        )


def test_material_row_corruption_in_small_payload_remains_fail_closed() -> None:
    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid in-scope filing rows",
    ):
        ResilientSECEdgarProvider._filing_records(
            _payload(invalid_indexes={1, 2}),
            cik=CIK,
            retrieved_at=RETRIEVED_AT,
        )


def test_structural_column_misalignment_remains_fail_closed() -> None:
    payload = _payload(invalid_indexes=set())
    payload["filings"]["recent"]["form"].pop()  # type: ignore[index]

    with pytest.raises(SECEdgarProviderError, match="misaligned columns"):
        ResilientSECEdgarProvider._filing_records(
            payload,
            cik=CIK,
            retrieved_at=RETRIEVED_AT,
        )


def test_production_evidence_uses_the_resilient_sec_provider() -> None:
    paper_evidence._synchronize_runtime_bindings()

    assert paper_evidence.SECEdgarProvider is ResilientSECEdgarProvider
    assert (
        paper_evidence._implementation.SECEdgarProvider
        is ResilientSECEdgarProvider
    )
