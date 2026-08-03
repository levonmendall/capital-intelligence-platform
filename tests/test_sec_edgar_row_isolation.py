"""Regression coverage for isolated malformed SEC filing rows."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import production_paper_evidence as paper_evidence
from providers.sec_edgar import SECEdgarProviderError
from providers.sec_edgar_resilient import ResilientSECEdgarProvider


CIK = "0000320193"
RETRIEVED_AT = datetime(2026, 8, 3, 15, 30, tzinfo=timezone.utc)


def _payload(*, invalid_indexes: set[int]) -> dict[str, object]:
    row_count = 3
    acceptance = [
        "2026-07-31T16:30:00-04:00",
        "2025-10-31T16:30:00-04:00",
        "2024-11-01T16:30:00-04:00",
    ]
    for index in invalid_indexes:
        acceptance[index] = "not-a-timestamp"
    return {
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-26-000001",
                    "0000320193-25-000001",
                    "0000320193-24-000001",
                ],
                "filingDate": ["2026-07-31", "2025-10-31", "2024-11-01"],
                "reportDate": ["2026-06-30", "2025-09-30", "2024-09-30"],
                "acceptanceDateTime": acceptance,
                "form": ["10-Q", "10-K", "10-K"],
                "primaryDocument": ["q2.htm", "annual.htm", "prior.htm"],
            }
        }
    }


def test_one_malformed_historical_filing_does_not_discard_valid_rows() -> None:
    records = ResilientSECEdgarProvider._filing_records(
        _payload(invalid_indexes={1}),
        cik=CIK,
        retrieved_at=RETRIEVED_AT,
    )

    assert [record.accession_number for record in records] == [
        "0000320193-26-000001",
        "0000320193-24-000001",
    ]
    assert all(record.retrieved_at == RETRIEVED_AT for record in records)


def test_material_row_corruption_remains_fail_closed() -> None:
    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid filing rows",
    ):
        ResilientSECEdgarProvider._filing_records(
            _payload(invalid_indexes={0, 1}),
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
