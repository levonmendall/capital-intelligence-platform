"""Provider-backed paper-evidence collection owned by the continuous evidence plane."""

from __future__ import annotations

from typing import Mapping, Sequence

from cio import CandidateAssetClass
from data import FilingQuery
from operations.direct_global_markets import DirectGlobalMarketClient, DirectGlobalMarketUniverse
from operations.free_paper_pilot import instrument_evaluation_scheduled
from operations.paper_evidence_spool_concurrent import collect_spooled_paper_evidence
from operations.persistent_alpaca_paper_history import PersistentAlpacaPaperHistoryClient
from providers.alpaca_paper_resilient import create_complete_alpaca_paper_client
from providers.fred import FREDProvider
from providers.sec_edgar_resilient import ResilientSECEdgarProvider

_HISTORY_DAYS = 365 * 10 + 20


def collect_owned_paper_evidence(
    universe,
    decision_as_of,
    *,
    required_holding_symbols: Sequence[str] = (),
    values: Mapping[str, str] | None = None,
):
    """Run the heavy provider collector only from the evidence-owner process."""

    def create_alpaca():
        return PersistentAlpacaPaperHistoryClient(
            create_complete_alpaca_paper_client(),
            values=values,
        )

    return collect_spooled_paper_evidence(
        universe,
        decision_as_of,
        create_alpaca_client=create_alpaca,
        sec_provider_factory=ResilientSECEdgarProvider,
        fred_provider_factory=FREDProvider,
        direct_market_client_type=DirectGlobalMarketClient,
        direct_market_universe_type=DirectGlobalMarketUniverse,
        filing_query_type=FilingQuery,
        candidate_asset_class=CandidateAssetClass,
        instrument_evaluation_scheduled=instrument_evaluation_scheduled,
        history_days=_HISTORY_DAYS,
        required_holding_symbols=required_holding_symbols,
    )


__all__ = ["collect_owned_paper_evidence"]
