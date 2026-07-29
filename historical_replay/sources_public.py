"""Official/public event, filing, positioning, fiscal, and news adapters."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from .http import HttpClient
from .models import HistoricalRecord, SourceResult, utc_now
from .sources import HistoricalSource

UTC = timezone.utc


def _iso_date(value: object) -> str:
    return str(value)[:10]

class WorldBankSource(HistoricalSource):
    name = "world_bank"

    def __init__(self, client: HttpClient, indicators: Iterable[str], countries: Iterable[str]) -> None:
        self.client = client
        self.indicators = tuple(dict.fromkeys(map(str, indicators)))
        self.countries = tuple(dict.fromkeys(str(item).upper() for item in countries))

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        records: list[HistoricalRecord] = []
        retrieved = utc_now()
        try:
            for country in self.countries:
                for indicator in self.indicators:
                    payload = self.client.get(f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}", params={"format": "json", "date": f"{start.year}:{end.year}", "per_page": 1000}).json()
                    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
                    for item in rows or []:
                        if item.get("value") is None:
                            continue
                        observed = f"{item['date']}-12-31"
                        records.append(HistoricalRecord(source=self.name, dataset=f"indicator.{indicator.lower()}", observed_at=observed, available_at=observed, retrieved_at=retrieved, strict_replay_eligible=False, payload={"country": country, "indicator": indicator, "value": item["value"]}, provenance_url="https://data.worldbank.org/", limitations=("exact_publication_timestamp_unavailable", "annual_revision_policy_not_point_in_time")))
                        if len(records) >= max_records:
                            return SourceResult(self.name, "degraded", tuple(records), warnings=("max_records_reached",))
            return SourceResult(self.name, "available", tuple(records))
        except Exception as error:
            return self._degraded(records, error)


class FederalRegisterSource(HistoricalSource):
    name = "federal_register"

    def __init__(self, client: HttpClient, terms: Iterable[str]) -> None:
        self.client = client
        self.terms = tuple(dict.fromkeys(str(item).strip() for item in terms if str(item).strip()))

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        records: list[HistoricalRecord] = []
        retrieved = utc_now()
        try:
            for term in self.terms:
                page = 1
                while len(records) < max_records:
                    payload = self.client.get("https://www.federalregister.gov/api/v1/documents.json", params={"conditions[term]": term, "conditions[publication_date][gte]": start.isoformat(), "conditions[publication_date][lte]": end.isoformat(), "per_page": 1000, "page": page, "order": "oldest"}).json()
                    rows = payload.get("results", [])
                    if not rows:
                        break
                    for item in rows:
                        observed = item.get("publication_date")
                        if not observed:
                            continue
                        records.append(HistoricalRecord(source=self.name, dataset="documents", observed_at=observed, available_at=observed, retrieved_at=retrieved, strict_replay_eligible=True, payload={"term": term, "document_number": item.get("document_number"), "title": item.get("title"), "type": item.get("type"), "agencies": item.get("agencies"), "html_url": item.get("html_url")}, provenance_url="https://www.federalregister.gov/", limitations=("availability_time_normalized_to_publication_date",)))
                        if len(records) >= max_records:
                            return SourceResult(self.name, "degraded", tuple(records), warnings=("max_records_reached",))
                    page += 1
                    if page > int(payload.get("total_pages") or page - 1):
                        break
            return SourceResult(self.name, "available", tuple(records))
        except Exception as error:
            return self._degraded(records, error)


class SecCompanyFactsSource(HistoricalSource):
    name = "sec_edgar"

    def __init__(self, client: HttpClient, ciks: Iterable[str]) -> None:
        self.client = client
        self.ciks = tuple(dict.fromkeys(str(item).zfill(10) for item in ciks))

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        records: list[HistoricalRecord] = []
        retrieved = utc_now()
        try:
            for cik in self.ciks:
                payload = self.client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").json()
                entity = payload.get("entityName")
                for taxonomy, concepts in payload.get("facts", {}).items():
                    for concept, detail in concepts.items():
                        for unit, facts in detail.get("units", {}).items():
                            for item in facts:
                                filed = item.get("filed")
                                observed = item.get("end") or item.get("start")
                                if not filed or not observed or not (start <= date.fromisoformat(filed) <= end):
                                    continue
                                records.append(HistoricalRecord(source=self.name, dataset=f"company_facts.{taxonomy.lower()}.{concept.lower()}", observed_at=observed, available_at=filed, retrieved_at=retrieved, strict_replay_eligible=True, payload={"cik": cik, "entity": entity, "taxonomy": taxonomy, "concept": concept, "unit": unit, "value": item.get("val"), "form": item.get("form"), "filed": filed, "accession": item.get("accn"), "fiscal_year": item.get("fy"), "fiscal_period": item.get("fp")}, provenance_url="https://www.sec.gov/edgar/sec-api-documentation", limitations=("filing_date_used_as_availability_boundary",)))
                                if len(records) >= max_records:
                                    return SourceResult(self.name, "degraded", tuple(records), warnings=("max_records_reached",))
            return SourceResult(self.name, "available", tuple(records))
        except Exception as error:
            return self._degraded(records, error)


class CftcSource(HistoricalSource):
    name = "cftc"

    def __init__(self, client: HttpClient, dataset_id: str = "gpe5-46if") -> None:
        self.client = client
        self.dataset_id = dataset_id

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        records: list[HistoricalRecord] = []
        retrieved = utc_now()
        try:
            offset = 0
            while len(records) < max_records:
                rows = self.client.get(f"https://publicreporting.cftc.gov/resource/{self.dataset_id}.json", params={"$where": f"report_date_as_yyyy_mm_dd between '{start.isoformat()}T00:00:00.000' and '{end.isoformat()}T23:59:59.999'", "$limit": min(50000, max_records - len(records)), "$offset": offset, "$order": "report_date_as_yyyy_mm_dd"}).json()
                if not rows:
                    break
                for item in rows:
                    observed = _iso_date(item.get("report_date_as_yyyy_mm_dd"))
                    records.append(HistoricalRecord(source=self.name, dataset=f"tff_futures_only.{self.dataset_id}", observed_at=observed, available_at=observed, retrieved_at=retrieved, strict_replay_eligible=False, payload=dict(item), provenance_url="https://publicreporting.cftc.gov/", limitations=("exact_publication_timestamp_unavailable", "same_day_availability_assumed")))
                offset += len(rows)
                if len(rows) < min(50000, max_records - min(len(records), max_records)):
                    break
            state = "degraded" if len(records) >= max_records else "available"
            return SourceResult(self.name, state, tuple(records[:max_records]), warnings=(("max_records_reached",) if state == "degraded" else ()))
        except Exception as error:
            return self._degraded(records, error)


class TreasuryFiscalDataSource(HistoricalSource):
    name = "treasury_fiscal_data"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        records: list[HistoricalRecord] = []
        retrieved = utc_now()
        try:
            page = 1
            while len(records) < max_records:
                payload = self.client.get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny", params={"filter": f"record_date:gte:{start.isoformat()},record_date:lte:{end.isoformat()}", "sort": "record_date", "page[number]": page, "page[size]": min(10000, max_records - len(records))}).json()
                rows = payload.get("data", [])
                if not rows:
                    break
                for item in rows:
                    observed = item.get("record_date")
                    if observed:
                        records.append(HistoricalRecord(source=self.name, dataset="debt_to_penny", observed_at=observed, available_at=observed, retrieved_at=retrieved, strict_replay_eligible=False, payload=dict(item), provenance_url="https://fiscaldata.treasury.gov/", limitations=("publication_time_not_provided", "same_day_availability_assumed")))
                total_pages = int(payload.get("meta", {}).get("total-pages") or page)
                if page >= total_pages:
                    break
                page += 1
            state = "degraded" if len(records) >= max_records else "available"
            return SourceResult(self.name, state, tuple(records[:max_records]), warnings=(("max_records_reached",) if state == "degraded" else ()))
        except Exception as error:
            return self._degraded(records, error)


class GdeltSource(HistoricalSource):
    name = "gdelt"

    def __init__(self, client: HttpClient, queries: Iterable[str]) -> None:
        self.client = client
        self.queries = tuple(dict.fromkeys(str(item).strip() for item in queries if str(item).strip()))

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        bounded_start = max(start, end - timedelta(days=89))
        records: list[HistoricalRecord] = []
        retrieved = utc_now()
        warnings = ["source_history_limited_to_recent_window"] if bounded_start > start else []
        try:
            for query in self.queries:
                payload = self.client.get("https://api.gdeltproject.org/api/v2/doc/doc", params={"query": query, "mode": "artlist", "format": "json", "maxrecords": min(250, max_records - len(records)), "startdatetime": bounded_start.strftime("%Y%m%d000000"), "enddatetime": end.strftime("%Y%m%d235959"), "sort": "datedesc"}).json()
                for item in payload.get("articles", []):
                    seen = item.get("seendate") or item.get("date")
                    if not seen:
                        continue
                    try:
                        observed = datetime.strptime(str(seen)[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
                    except ValueError:
                        observed = datetime.combine(date.fromisoformat(str(seen)[:10]), datetime.min.time(), tzinfo=UTC)
                    records.append(HistoricalRecord(source=self.name, dataset="news_discovery", observed_at=observed, available_at=observed, retrieved_at=retrieved, strict_replay_eligible=False, payload={"query": query, "title": item.get("title"), "url": item.get("url"), "domain": item.get("domain"), "language": item.get("language"), "sourcecountry": item.get("sourcecountry")}, provenance_url="https://www.gdeltproject.org/", limitations=("discovery_metadata_only", "rolling_history_window", "requires_independent_corroboration")))
                    if len(records) >= max_records:
                        return SourceResult(self.name, "degraded", tuple(records), warnings=tuple(warnings + ["max_records_reached"]))
            return SourceResult(self.name, "degraded" if warnings else "available", tuple(records), warnings=tuple(warnings))
        except Exception as error:
            return SourceResult(self.name, "degraded", tuple(records), warnings=tuple(warnings + [f"collection_error:{type(error).__name__}"]))
