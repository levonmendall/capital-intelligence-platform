"""Bounded row isolation for official SEC EDGAR filing submissions.

The SEC submissions endpoint uses parallel arrays. A single malformed historical row
must not discard hundreds of valid filings or abort the entire cross-market evidence
collection. Structural payload failures and material row corruption remain fail-closed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from data import FilingRecord
from providers.sec_edgar import SECEdgarProvider, SECEdgarProviderError


_LOGGER = logging.getLogger("capital_intelligence.providers.sec_edgar")
_ROW_POLICY_VERSION = "sec-edgar-filing-row-isolation.v1"


class ResilientSECEdgarProvider(SECEdgarProvider):
    """Use valid SEC filing rows while rejecting materially corrupted payloads."""

    row_policy_version = _ROW_POLICY_VERSION

    @classmethod
    def _filing_records(
        cls,
        payload: dict[str, Any],
        *,
        cik: str,
        retrieved_at: datetime,
    ) -> tuple[FilingRecord, ...]:
        filings = payload.get("filings")
        recent = filings.get("recent") if isinstance(filings, dict) else None
        if not isinstance(recent, dict):
            raise SECEdgarProviderError(
                f"SEC returned invalid submissions for {cik}."
            )

        required_columns = (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
        )
        columns: dict[str, list[object]] = {}
        for name in required_columns:
            column = recent.get(name)
            if not isinstance(column, list):
                raise SECEdgarProviderError(
                    f"SEC submissions are missing {name}."
                )
            columns[name] = column

        lengths = {len(column) for column in columns.values()}
        if len(lengths) != 1:
            raise SECEdgarProviderError(
                "SEC submissions contain misaligned columns."
            )
        row_count = lengths.pop()
        if row_count == 0:
            return ()

        records: list[FilingRecord] = []
        invalid_indexes: list[int] = []
        for index in range(row_count):
            try:
                raw_accession = columns["accessionNumber"][index]
                raw_document = columns["primaryDocument"][index]
                raw_form = columns["form"][index]
                if not isinstance(raw_accession, str) or not raw_accession.strip():
                    raise ValueError("accessionNumber is unavailable")
                if not isinstance(raw_document, str) or not raw_document.strip():
                    raise ValueError("primaryDocument is unavailable")
                if not isinstance(raw_form, str) or not raw_form.strip():
                    raise ValueError("form is unavailable")

                accession_number = raw_accession.strip()
                primary_document = raw_document.strip()
                form = raw_form.strip().upper()
                records.append(
                    FilingRecord(
                        cik=cik,
                        accession_number=accession_number,
                        form=form,
                        accepted_at=cls._parse_acceptance(
                            columns["acceptanceDateTime"][index]
                        ),
                        filing_date=cls._parse_date(
                            columns["filingDate"][index],
                            field_name="filingDate",
                        ),
                        report_date=cls._optional_date(
                            columns["reportDate"][index],
                            field_name="reportDate",
                        ),
                        primary_document=primary_document,
                        retrieved_at=retrieved_at,
                        source_url=cls._filing_url(
                            cik,
                            accession_number,
                            primary_document,
                        ),
                    )
                )
            except (TypeError, ValueError):
                invalid_indexes.append(index)

        # Permit an isolated bad row, but do not normalize a materially corrupted
        # SEC submission into apparently complete evidence. The tolerance is one
        # percent of the payload, with a minimum allowance of one row.
        allowed_invalid = max(1, row_count // 100)
        if not records or len(invalid_indexes) > allowed_invalid:
            sample = ", ".join(str(value) for value in invalid_indexes[:10])
            raise SECEdgarProviderError(
                "SEC submissions contain excessive invalid filing rows for "
                f"{cik}: invalid={len(invalid_indexes)}, total={row_count}, "
                f"allowed={allowed_invalid}, indexes={sample or 'none'}."
            )

        if invalid_indexes:
            _LOGGER.warning(
                "isolated malformed SEC filing rows",
                extra={
                    "cik": cik,
                    "invalid_filing_count": len(invalid_indexes),
                    "filing_row_count": row_count,
                    "invalid_filing_indexes": invalid_indexes[:10],
                    "policy_version": cls.row_policy_version,
                    "real_money_authorized": False,
                },
            )
        return tuple(records)


__all__ = ["ResilientSECEdgarProvider"]
