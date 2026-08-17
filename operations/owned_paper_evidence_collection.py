"""Provider-backed paper-evidence collection owned by the continuous evidence plane."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence

from cio import CandidateAssetClass
from data import FilingQuery
from operations.direct_global_markets import DirectGlobalMarketClient, DirectGlobalMarketUniverse
from operations.free_paper_pilot import (
    assess_free_paper_pilot_readiness,
    instrument_evaluation_scheduled,
    load_free_paper_pilot_universe,
)
from operations.paper_evidence_spool_concurrent import collect_spooled_paper_evidence
from operations.persistent_alpaca_paper_history import PersistentAlpacaPaperHistoryClient
from providers.alpaca_paper_resilient import create_complete_alpaca_paper_client
from providers.fred import FREDProvider
from providers.fred_cache import JsonFREDCache
from providers.persistent_sec_company_facts import PersistentSECCompanyFactsProvider

_HISTORY_DAYS = 365 * 10 + 20


def _readiness_payload(report) -> dict[str, object]:
    """Persist only the governed readiness facts needed by provider-free consumers."""

    return {
        "evaluated_at": report.evaluated_at.isoformat(),
        "universe_identifier": report.universe_identifier,
        "configuration_ready": report.configuration_ready,
        "execution_ready_now": report.execution_ready_now,
        "market_open": report.market_open,
        "account_status": report.account_status,
        "validated_symbols": list(report.validated_symbols),
        "quote_timestamps": [list(item) for item in report.quote_timestamps],
        "blockers": list(report.blockers),
        "warnings": list(report.warnings),
    }


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
    Broker/account/asset readiness is acquired here as well and embedded into the same
    immutable evidence handoff so downstream CIO consumers never need provider I/O.
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

    payload = dict(
        collect_spooled_paper_evidence(
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
    )

    # Preserve the existing paper-readiness contract (ACTIVE/unblocked paper account,
    # active+tradable listed assets and qualified quotes) while moving the external calls
    # into the single evidence owner. The readiness result is release-independent data,
    # not investment or execution authority.
    readiness = assess_free_paper_pilot_readiness(
        universe=load_free_paper_pilot_universe(),
        client=create_complete_alpaca_paper_client(),
    )
    provider_clock = payload.get("provider_clock", {})
    if not isinstance(provider_clock, Mapping):
        raise TypeError("owned paper evidence provider clock is malformed")
    payload["provider_clock"] = {
        **dict(provider_clock),
        "paper_readiness": _readiness_payload(readiness),
    }
    return payload


__all__ = ["collect_owned_paper_evidence"]
