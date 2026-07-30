"""Free/public historical-source interface and configured source factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Mapping, Sequence

from .http import HttpClient
from .models import HistoricalRecord, SourceResult


class HistoricalSource(ABC):
    name: str

    @abstractmethod
    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        raise NotImplementedError

    def _degraded(
        self,
        records: Sequence[HistoricalRecord],
        error: Exception,
    ) -> SourceResult:
        """Preserve valid partial evidence while reporting a credential-safe outage."""

        warning = f"collection_error:{type(error).__name__}"
        if records:
            return SourceResult(
                self.name,
                "degraded",
                tuple(records),
                warnings=(warning,),
            )
        return SourceResult(
            self.name,
            "unavailable",
            blockers=(warning,),
        )


def build_sources(config: Mapping[str, Any], *, user_agent: str) -> tuple[HistoricalSource, ...]:
    from .sources_cboe import CboeVixSource
    from .sources_fred import FredSource
    from .sources_market import CoinbaseSource, StooqSource
    from .sources_public import (
        CftcSource,
        FederalRegisterSource,
        GdeltSource,
        SecCompanyFactsSource,
        TreasuryFiscalDataSource,
        WorldBankSource,
    )

    client = HttpClient(user_agent=user_agent)
    enabled = config.get("sources", {})
    sources: list[HistoricalSource] = []
    if enabled.get("fred", {}).get("enabled", True):
        sources.append(FredSource(client, enabled.get("fred", {}).get("series", [])))
    if enabled.get("cboe_vix", {}).get("enabled", False):
        sources.append(CboeVixSource(client))
    if enabled.get("coinbase", {}).get("enabled", True):
        sources.append(CoinbaseSource(client, enabled.get("coinbase", {}).get("products", [])))
    if enabled.get("stooq", {}).get("enabled", True):
        sources.append(StooqSource(client, enabled.get("stooq", {}).get("symbols", [])))
    if enabled.get("world_bank", {}).get("enabled", True):
        item = enabled.get("world_bank", {})
        sources.append(WorldBankSource(client, item.get("indicators", []), item.get("countries", [])))
    if enabled.get("federal_register", {}).get("enabled", True):
        sources.append(FederalRegisterSource(client, enabled.get("federal_register", {}).get("terms", [])))
    if enabled.get("sec_edgar", {}).get("enabled", True):
        sources.append(SecCompanyFactsSource(client, enabled.get("sec_edgar", {}).get("ciks", [])))
    if enabled.get("cftc", {}).get("enabled", True):
        sources.append(CftcSource(client, enabled.get("cftc", {}).get("dataset_id", "gpe5-46if")))
    if enabled.get("treasury_fiscal_data", {}).get("enabled", True):
        sources.append(TreasuryFiscalDataSource(client))
    if enabled.get("gdelt", {}).get("enabled", True):
        sources.append(GdeltSource(client, enabled.get("gdelt", {}).get("queries", [])))
    return tuple(sources)
