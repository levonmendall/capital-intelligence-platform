"""Scope-aware row isolation for official SEC EDGAR filing submissions.

The SEC submissions endpoint uses parallel arrays. Malformed rows outside the filing
forms requested by a point-in-time query must not block that query. Malformed rows
inside the requested evidence scope remain bounded and fail closed when structural or
material corruption is present.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from data import CompanyFact, FilingQuery, FilingRecord
from providers.sec_edgar import (
    SEC_COMPANY_FACTS_URL,
    SECEdgarProvider,
    SECEdgarProviderError,
)


_LOGGER = logging.getLogger("capital_intelligence.providers.sec_edgar")
_ROW_POLICY_VERSION = "sec-edgar-filing-row-isolation.v4"
_MINIMUM_TRAILING_POLICY_ROWS = 100


class ResilientSECEdgarProvider(SECEdgarProvider):
    """Use valid in-scope SEC rows while rejecting material corruption."""

    row_policy_version = _ROW_POLICY_VERSION

    def fetch_filings(self, query: FilingQuery) -> tuple[FilingRecord, ...]:
        """Return requested filings without parsing unrelated form families."""

        self._validate_query(query)
        retrieved_at = self._retrieved_at()
        payload = self._submissions_payload(query.cik)
        records = tuple(
            record
            for record in self._filing_records(
                payload,
                cik=query.cik,
                retrieved_at=retrieved_at,
                forms=query.forms,
            )
            if record.accepted_at <= query.as_of
        )
        ordered = sorted(
            records,
            key=lambda record: (
                record.accepted_at,
                record.accession_number,
            ),
            reverse=True,
        )
        return tuple(ordered[: query.limit])

    def fetch_company_facts(self, query: FilingQuery) -> tuple[CompanyFact, ...]:
        """Join facts only to filing forms included in the governed query."""

        self._validate_query(query)
        retrieved_at = self._retrieved_at()
        submissions = self._submissions_payload(query.cik)
        filings = self._filing_records(
            submissions,
            cik=query.cik,
            retrieved_at=retrieved_at,
            forms=query.forms,
        )
        accepted_by_accession = {
            record.accession_number: record.accepted_at
            for record in filings
        }
        payload = self._request_payload(
            SEC_COMPANY_FACTS_URL.format(cik=query.cik),
            resource=f"company facts for {query.cik}",
        )
        facts = payload.get("facts")
        if not isinstance(facts, dict):
            raise SECEdgarProviderError(
                f"SEC returned invalid company facts for {query.cik}."
            )

        normalized: list[CompanyFact] = []
        for taxonomy, taxonomy_facts in facts.items():
            if not isinstance(taxonomy_facts, dict):
                continue
            for tag, concept in taxonomy_facts.items():
                if not isinstance(concept, dict):
                    continue
                units = concept.get("units")
                if not isinstance(units, dict):
                    continue
                normalized.extend(
                    self._company_fact_units(
                        cik=query.cik,
                        taxonomy=str(taxonomy),
                        tag=str(tag),
                        units=units,
                        accepted_by_accession=accepted_by_accession,
                        query=query,
                        retrieved_at=retrieved_at,
                    )
                )

        normalized.sort(
            key=lambda fact: (
                fact.accepted_at,
                fact.accession_number,
                fact.taxonomy,
                fact.tag,
                fact.unit,
                fact.period_end,
            ),
            reverse=True,
        )
        return tuple(normalized[: query.limit])

    @classmethod
    def _filing_records(
        cls,
        payload: dict[str, Any],
        *,
        cik: str,
        retrieved_at: datetime,
        forms: tuple[str, ...] = (),
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

        form_scope = frozenset(form.strip().upper() for form in forms)
        records: list[FilingRecord] = []
        relevant_indexes: list[int] = []
        invalid_indexes: list[int] = []
        for index in range(row_count):
            raw_form = columns["form"][index]
            if not isinstance(raw_form, str) or not raw_form.strip():
                # A missing form cannot be proven out of scope, so retain strict
                # treatment rather than silently discarding the row.
                relevant_indexes.append(index)
                invalid_indexes.append(index)
                continue
            form = raw_form.strip().upper()
            if form_scope and form not in form_scope:
                continue
            relevant_indexes.append(index)

            try:
                raw_accession = columns["accessionNumber"][index]
                raw_document = columns["primaryDocument"][index]
                if not isinstance(raw_accession, str) or not raw_accession.strip():
                    raise ValueError("accessionNumber is unavailable")
                if not isinstance(raw_document, str) or not raw_document.strip():
                    raise ValueError("primaryDocument is unavailable")

                accession_number = raw_accession.strip()
                primary_document = raw_document.strip()
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

        relevant_count = len(relevant_indexes)
        if relevant_count == 0:
            return ()

        ordinary_allowed = max(1, relevant_count // 100)
        trailing_suffix = bool(invalid_indexes) and invalid_indexes == relevant_indexes[
            -len(invalid_indexes) :
        ]
        trailing_allowed = max(ordinary_allowed, relevant_count // 50)
        trailing_policy_applies = (
            relevant_count >= _MINIMUM_TRAILING_POLICY_ROWS and trailing_suffix
        )
        allowed_invalid = (
            trailing_allowed if trailing_policy_applies else ordinary_allowed
        )

        # Bounds apply only to requested forms. Unrequested rows are not evidence for
        # this query and therefore are not normalized, counted, or allowed to veto it.
        if not records or len(invalid_indexes) > allowed_invalid:
            sample = ", ".join(str(value) for value in invalid_indexes[:10])
            raise SECEdgarProviderError(
                "SEC submissions contain excessive invalid in-scope filing rows for "
                f"{cik}: invalid={len(invalid_indexes)}, relevant={relevant_count}, "
                f"total={row_count}, allowed={allowed_invalid}, "
                f"trailing_suffix={trailing_suffix}, indexes={sample or 'none'}."
            )

        if invalid_indexes:
            _LOGGER.warning(
                "isolated malformed SEC filing rows",
                extra={
                    "cik": cik,
                    "invalid_filing_count": len(invalid_indexes),
                    "relevant_filing_row_count": relevant_count,
                    "filing_row_count": row_count,
                    "invalid_filing_indexes": invalid_indexes[:10],
                    "requested_forms": sorted(form_scope),
                    "trailing_suffix": trailing_suffix,
                    "allowed_invalid_filing_count": allowed_invalid,
                    "policy_version": cls.row_policy_version,
                    "real_money_authorized": False,
                },
            )
        return tuple(records)


__all__ = ["ResilientSECEdgarProvider"]
