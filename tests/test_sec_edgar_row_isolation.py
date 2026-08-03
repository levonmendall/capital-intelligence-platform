"""Regression coverage for isolated malformed SEC filing rows."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import production_paper_evidence as paper_evidence
from providers.sec_edgar import SECEdgarProviderError
from providers.sec_edgar_resilient import ResilientSECEdgarProvider


CIK = "0000320193"
RETRIEVED_AT = datetime(2026, 8, 3, 15, 30, tzinfo=timezone.utc)


def _payload(
    *,
    invalid_indexes: set[int],
    row_count: int = 3,
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
                "form": ["10-K"] * row_count,
                "primaryDocument": [
                    f"filing-{index}.htm"
                    for index in range(row_count)
                ],
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


def test_same_invalid_count_scattered_through_history_remains_fail_closed() -> None:
    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid filing rows",
    ):
        ResilientSECEdgarProvider._filing_records(
            _payload(
                row_count=993,
                invalid_indexes={100, 200, 300, 400, 500, 600, 700, 800, 900, 950, 992},
            ),
            cik="0000311337",
            retrieved_at=RETRIEVED_AT,
        )


def test_trailing_legacy_suffix_over_two_percent_remains_fail_closed() -> None:
    with pytest.raises(
        SECEdgarProviderError,
        match="excessive invalid filing rows",
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
        match="excessive invalid filing rows",
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
