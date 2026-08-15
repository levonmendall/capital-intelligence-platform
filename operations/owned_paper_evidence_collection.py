"""Provider-backed paper-evidence collection owned by the continuous evidence plane."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence

from cio import CandidateAssetClass
from data import FilingQuery
from operations.direct_global_markets import DirectGlobalMarketClient, DirectGlobalMarketUniverse
from operations.free_paper_pilot import instrument_evaluation_scheduled
from operations.paper_evidence_spool_concurrent import collect_spooled_paper_evidence
from operations.persistent_alpaca_paper_history import PersistentAlpacaPaperHistoryClient
from providers.alpaca_paper_resilient import create_complete_alpaca_paper_client
from providers.fred import FREDProvider
from providers.fred_cache import JsonFREDCache
from providers.persistent_sec_company_facts import PersistentSECCompanyFactsProvider

_HISTORY_DAYS = 365 * 10 + 20


def collect_owned_paper_evidence(
    universe,
    decision_as_of,
    *,
    required_holding_symbols: Sequence[str] = (),
    values: Mapping[str, str] | None = None,
):
    """Run the heavy provider collector only from the evidence-owner process.

    Immutable daily history and slow-changing SEC/FRED evidence are cached persistently
    across short-lived collection children. Quotes remain live on each qualified refresh.
    """

    resolved = dict(os.environ if values is None else values)

    def create_alpaca():
        return PersistentAlpacaPaperHistoryClient(
            create_complete_alpaca_paper_client(),
            values=resolved,
        )

    def create_sec():
        return PersistentSECCompanyFactsProvider(values=resolved)

    def create_fred():
        data_dir = resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
        cache = None
        if data_dir:
            cache = JsonFREDCache(
                Path(data_dir).expanduser() / "fred_cache" / "paper-evidence.json"
            )
        return FREDProvider(cache=cache) if cache is not None else FREDProvider()

    return collect_spooled_paper_evidence(
        universe,
        decision_as_of,
        create_alpaca_client=create_alpaca,
        sec_provider_factory=create_sec,
        fred_provider_factory=create_fred,
        direct_market_client_type=DirectGlobalMarketClient,
        direct_market_universe_type=DirectGlobalMarketUniverse,
        filing_query_type=FilingQuery,
        candidate_asset_class=CandidateAssetClass,
        instrument_evaluation_scheduled=instrument_evaluation_scheduled,
        history_days=_HISTORY_DAYS,
        required_holding_symbols=required_holding_symbols,
    )


__all__ = ["collect_owned_paper_evidence"]
