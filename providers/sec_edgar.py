"""Official SEC EDGAR provider with point-in-time acceptance controls."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from data import (
    AssetClass,
    CompanyFact,
    FilingProviderError,
    FilingQuery,
    FilingRecord,
    IdentifierScheme,
    Instrument,
    InstrumentIdentifier,
    InstrumentType,
    Issuer,
    SecurityMasterCatalog,
    SecurityMasterCoverage,
    SecurityMasterSnapshot,
    TradingCalendar,
    VenueListing,
    normalize_cik,
)


SEC_SUBMISSIONS_URL = (
    "https://data.sec.gov/submissions/CIK{cik}.json"
)
SEC_COMPANY_FACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)
SEC_TICKERS_URL = (
    "https://www.sec.gov/files/company_tickers_exchange.json"
)
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_TIMEZONE = ZoneInfo("America/New_York")


class SECEdgarProviderError(FilingProviderError):
    """Raised when SEC EDGAR data cannot be retrieved or interpreted."""


class SECEdgarProvider:
    """Retrieve official SEC submissions, identities, and XBRL facts."""

    def __init__(
        self,
        user_agent: str | None = None,
        timeout: int = 20,
        *,
        clock: Callable[[], datetime] | None = None,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT")
        self.timeout = timeout
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._http_get = http_get or requests.get

    @property
    def name(self) -> str:
        """Stable provider identifier."""

        return "SEC_EDGAR"

    @property
    def configured(self) -> bool:
        """Return whether the required SEC identity header is available."""

        return bool(self.user_agent)

    def fetch_security_master(self) -> SecurityMasterSnapshot:
        """Return the current SEC ticker-exchange identity snapshot."""

        retrieved_at = self._retrieved_at()
        payload = self._request_payload(
            SEC_TICKERS_URL,
            resource="company ticker exchange file",
        )
        fields = payload.get("fields")
        rows = payload.get("data")
        if not isinstance(fields, list) or not isinstance(rows, list):
            raise SECEdgarProviderError(
                "SEC returned an invalid security-master payload."
            )

        required = ("cik", "name", "ticker", "exchange")
        indexes = self._field_indexes(fields, required)
        issuers: dict[str, Issuer] = {}
        instruments: list[Instrument] = []
        listings: list[VenueListing] = []
        for row in rows:
            if not isinstance(row, list):
                continue
            try:
                cik = normalize_cik(row[indexes["cik"]])
                name = str(row[indexes["name"]])
                ticker = str(row[indexes["ticker"]]).upper()
                exchange = (
                    str(row[indexes["exchange"]]).upper()
                    if row[indexes["exchange"]]
                    else "UNKNOWN"
                )
                issuer_id = f"SEC:CIK:{cik}"
                issuers.setdefault(
                    issuer_id,
                    Issuer(
                        issuer_id=issuer_id,
                        name=name,
                        identifiers=(
                            InstrumentIdentifier(
                                scheme=IdentifierScheme.CIK,
                                value=cik,
                                provider=self.name,
                            ),
                        ),
                    ),
                )
                instrument_id = (
                    f"{issuer_id}:LISTING:{exchange}:{ticker}"
                )
                instruments.append(
                    Instrument(
                        instrument_id=instrument_id,
                        name=name,
                        asset_class=AssetClass.UNKNOWN,
                        instrument_type=InstrumentType.OTHER,
                        issuer_id=issuer_id,
                        identifiers=(
                            InstrumentIdentifier(
                                scheme=IdentifierScheme.TICKER,
                                value=ticker,
                                provider=self.name,
                            ),
                        ),
                    )
                )
                listings.append(
                    VenueListing(
                        instrument_id=instrument_id,
                        venue=exchange,
                        symbol=ticker,
                        trading_calendar=(
                            TradingCalendar.EXCHANGE
                        ),
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        if not instruments:
            raise SECEdgarProviderError(
                "SEC returned no usable security identities."
            )
        return SecurityMasterSnapshot(
            observed_at=retrieved_at,
            retrieved_at=retrieved_at,
            issuers=tuple(issuers.values()),
            instruments=tuple(instruments),
            listings=tuple(listings),
            source=self.name,
        )

    def fetch_security_master_catalog(self) -> SecurityMasterCatalog:
        """Return a current-only catalog with explicit non-authoritative coverage.

        The public SEC ticker-exchange file is useful identity evidence, but it
        does not provide licensed full-universe coverage, historical symbols,
        delistings, venue history, or a complete corporate-action history.
        """

        snapshot = self.fetch_security_master()
        return SecurityMasterCatalog.from_current_snapshot(
            snapshot,
            identifier=(
                "security-master:sec-edgar-current:"
                + snapshot.retrieved_at.isoformat()
            ),
            version="security-master.sec-current.v1",
            coverage=SecurityMasterCoverage(
                source=self.name,
                source_version="sec-company-tickers-exchange.current.v1",
                licensed=False,
                complete_universe=False,
                point_in_time=True,
                historical_identifiers=False,
                listing_history=False,
                delistings=False,
                corporate_actions=False,
                provenance_complete=True,
                service_level_defined=False,
            ),
        )

    def fetch_filings(
        self,
        query: FilingQuery,
    ) -> tuple[FilingRecord, ...]:
        """Return recent filings accepted by the query boundary."""

        self._validate_query(query)
        retrieved_at = self._retrieved_at()
        payload = self._submissions_payload(query.cik)
        records = tuple(
            record
            for record in self._filing_records(
                payload,
                cik=query.cik,
                retrieved_at=retrieved_at,
            )
            if record.accepted_at <= query.as_of
            and (
                not query.forms
                or record.form in query.forms
            )
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

    def fetch_company_facts(
        self,
        query: FilingQuery,
    ) -> tuple[CompanyFact, ...]:
        """Return XBRL facts joined to accepted filing timestamps."""

        self._validate_query(query)
        retrieved_at = self._retrieved_at()
        submissions = self._submissions_payload(query.cik)
        filings = tuple(
            self._filing_records(
                submissions,
                cik=query.cik,
                retrieved_at=retrieved_at,
            )
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

    def _submissions_payload(self, cik: str) -> dict[str, Any]:
        return self._request_payload(
            SEC_SUBMISSIONS_URL.format(cik=normalize_cik(cik)),
            resource=f"submissions for {normalize_cik(cik)}",
        )

    def _request_payload(
        self,
        url: str,
        *,
        resource: str,
    ) -> dict[str, Any]:
        if not self.user_agent:
            raise SECEdgarProviderError(
                "SEC_USER_AGENT is not configured. Use a descriptive "
                "application name and contact email."
            )
        try:
            response = self._http_get(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise SECEdgarProviderError(
                f"SEC request failed for {resource}: {error}"
            ) from error
        except ValueError as error:
            raise SECEdgarProviderError(
                f"SEC returned invalid JSON for {resource}."
            ) from error
        if not isinstance(payload, dict):
            raise SECEdgarProviderError(
                f"SEC returned an invalid payload for {resource}."
            )
        return payload

    def _retrieved_at(self) -> datetime:
        retrieved_at = self._clock()
        if (
            not isinstance(retrieved_at, datetime)
            or retrieved_at.tzinfo is None
            or retrieved_at.utcoffset() is None
        ):
            raise SECEdgarProviderError(
                "SEC provider clock must return a "
                "timezone-aware datetime."
            )
        return retrieved_at

    @staticmethod
    def _validate_query(query: FilingQuery) -> None:
        if not isinstance(query, FilingQuery):
            raise TypeError("query must be a FilingQuery")

    @staticmethod
    def _field_indexes(
        fields: list[object],
        required: tuple[str, ...],
    ) -> dict[str, int]:
        normalized = {
            str(field): index
            for index, field in enumerate(fields)
        }
        missing = set(required).difference(normalized)
        if missing:
            raise SECEdgarProviderError(
                "SEC security-master payload is missing fields: "
                + ", ".join(sorted(missing))
            )
        return {
            field: normalized[field]
            for field in required
        }

    @classmethod
    def _filing_records(
        cls,
        payload: dict[str, Any],
        *,
        cik: str,
        retrieved_at: datetime,
    ) -> Iterable[FilingRecord]:
        filings = payload.get("filings")
        recent = (
            filings.get("recent")
            if isinstance(filings, dict)
            else None
        )
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
        columns = {}
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

        for index in range(lengths.pop()):
            try:
                accession_number = str(
                    columns["accessionNumber"][index]
                )
                primary_document = str(
                    columns["primaryDocument"][index]
                )
                yield FilingRecord(
                    cik=cik,
                    accession_number=accession_number,
                    form=str(columns["form"][index]),
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
            except (TypeError, ValueError) as error:
                raise SECEdgarProviderError(
                    f"SEC returned an invalid filing at index {index}."
                ) from error

    @classmethod
    def _company_fact_units(
        cls,
        *,
        cik: str,
        taxonomy: str,
        tag: str,
        units: dict[str, Any],
        accepted_by_accession: dict[str, datetime],
        query: FilingQuery,
        retrieved_at: datetime,
    ) -> Iterable[CompanyFact]:
        for unit, entries in units.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                accession = entry.get("accn")
                accepted_at = accepted_by_accession.get(
                    str(accession)
                )
                form = str(entry.get("form", "")).upper()
                if (
                    accepted_at is None
                    or accepted_at > query.as_of
                    or (query.forms and form not in query.forms)
                ):
                    continue
                try:
                    yield CompanyFact(
                        cik=cik,
                        taxonomy=taxonomy,
                        tag=tag,
                        unit=str(unit),
                        value=entry.get("val"),
                        period_start=cls._optional_date(
                            entry.get("start"),
                            field_name="start",
                        ),
                        period_end=cls._parse_date(
                            entry.get("end"),
                            field_name="end",
                        ),
                        filed_at=cls._parse_date(
                            entry.get("filed"),
                            field_name="filed",
                        ),
                        accepted_at=accepted_at,
                        retrieved_at=retrieved_at,
                        accession_number=str(accession),
                        form=form,
                        fiscal_year=entry.get("fy"),
                        fiscal_period=entry.get("fp"),
                        frame=entry.get("frame"),
                    )
                except (TypeError, ValueError):
                    continue

    @staticmethod
    def _parse_acceptance(value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError(
                "acceptanceDateTime must be an ISO timestamp"
            )
        normalized = value.strip().replace("Z", "+00:00")
        accepted_at = datetime.fromisoformat(normalized)
        if accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=SEC_TIMEZONE)
        return accepted_at.astimezone(timezone.utc)

    @staticmethod
    def _parse_date(value: object, *, field_name: str) -> date:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be an ISO date")
        return date.fromisoformat(value)

    @classmethod
    def _optional_date(
        cls,
        value: object,
        *,
        field_name: str,
    ) -> date | None:
        if value in {None, ""}:
            return None
        return cls._parse_date(value, field_name=field_name)

    @staticmethod
    def _filing_url(
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> str:
        accession_path = accession_number.replace("-", "")
        return (
            f"{SEC_ARCHIVES_URL}/{int(normalize_cik(cik))}/"
            f"{quote(accession_path)}/{quote(primary_document)}"
        )
