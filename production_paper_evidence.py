"""Governed facade preserving paper-evidence compatibility and risk lineage.

The complete implementation remains in ``production_paper_evidence_impl``. This
facade preserves the historical module-level monkeypatch boundary used by tests and
operations while restoring derivative-risk truth, streaming full provider evidence
through a disk-backed cycle spool, and enriching every governed candidate with
point-in-time capital-flow and market-expectations intelligence.
"""

from __future__ import annotations

import threading
from dataclasses import replace

import intelligence.predictive_market as _predictive_market
import production_paper_evidence_impl as _implementation
from intelligence.predictive_market import (
    CapitalFlowEngine,
    CapitalFlowObservation,
    build_predictive_market_intelligence,
)
from intelligence.predictive_scenario_merge import (
    reconcile_forward_intelligence,
)
from operations.paper_evidence_spool_concurrent import (
    close_spooled_paper_evidence,
    collect_spooled_paper_evidence,
)
from providers.alpaca_paper_resilient import create_complete_alpaca_paper_client
from providers.sec_company_facts_availability import (
    install_company_facts_availability_boundary,
)
from providers.sec_edgar_resilient import ResilientSECEdgarProvider

_DERIVATIVE_WRAPPER_EXPOSURES = frozenset(
    {"managed_futures", "option_strategies", "volatility"}
)
_ORIGINAL_DEFAULT_PROBE = _implementation._default_probe
_ORIGINAL_COLLECT_PAPER_EVIDENCE = _implementation.collect_paper_evidence
_ORIGINAL_BUILD_PAPER_EVIDENCE = _implementation.build_paper_evidence
_ORIGINAL_FEATURES = _implementation._features
_ORIGINAL_CANDIDATE_AND_EVIDENCE = _implementation._candidate_and_evidence
_ORIGINAL_COMPANY_CANDIDATE_AND_EVIDENCE = (
    _implementation._company_candidate_and_evidence
)
_IMPLEMENTATION_NAMES = tuple(vars(_implementation))
_WRAPPED_NAMES = frozenset(
    {
        "_default_probe",
        "collect_paper_evidence",
        "build_paper_evidence",
        "_features",
        "_candidate_and_evidence",
        "_company_candidate_and_evidence",
        "create_alpaca_paper_client",
        "SECEdgarProvider",
    }
)
_FLOW_STATE = threading.local()


for _name, _value in vars(_implementation).items():
    if _name.startswith("__") or _name in _WRAPPED_NAMES:
        continue
    globals()[_name] = _value


_predictive_market.merge_forward_intelligence = reconcile_forward_intelligence
install_company_facts_availability_boundary()
create_alpaca_paper_client = create_complete_alpaca_paper_client
SECEdgarProvider = ResilientSECEdgarProvider


def _flow_registry() -> dict[tuple[str, str], CapitalFlowObservation]:
    values = getattr(_FLOW_STATE, "observations", None)
    if values is None:
        values = {}
        _FLOW_STATE.observations = values
    return values


def _flow_key(symbol: str, as_of) -> tuple[str, str]:
    return str(symbol).upper(), as_of.isoformat()


def _production_build_active() -> bool:
    return bool(getattr(_FLOW_STATE, "production_build", False))


def _compatibility_flow_observation(features, as_of) -> CapitalFlowObservation:
    """Return explicit neutral flow only for direct legacy helper compatibility.

    The governed production build never uses this path. It requires a raw-bar-derived
    observation from ``_features`` and fails closed when that observation is absent.
    Several historical unit tests call the lower candidate helper directly with an
    already-constructed feature record; this neutral observation keeps that narrow
    compatibility surface deterministic without pretending that market flow was
    observed.
    """

    symbol = str(features.symbol).upper()
    identifier = (
        f"derived-capital-flow-compatibility-only:{symbol}:{as_of.isoformat()}"
    )
    volatility = max(
        0.0,
        min(1.0, float(getattr(features, "annualized_volatility", 0.0))),
    )
    return CapitalFlowObservation(
        identifier=identifier,
        symbol=symbol,
        as_of=as_of,
        recent_volume_impulse=0.0,
        signed_dollar_flow=0.0,
        accumulation_distribution=0.0,
        price_volume_confirmation=0.0,
        persistence=0.50,
        short_trend=0.0,
        medium_trend=0.0,
        volatility=volatility,
        crowding=0.0,
        short_covering_likelihood=0.0,
        evidence_identifiers=tuple(
            dict.fromkeys(
                (
                    *tuple(getattr(features, "evidence_identifiers", ()) or ()),
                    identifier,
                )
            )
        ),
    )


def _synchronize_runtime_bindings() -> None:
    """Propagate facade monkeypatches into implementation function globals."""

    for name in _IMPLEMENTATION_NAMES:
        if name.startswith("__") or name in _WRAPPED_NAMES:
            continue
        if name in globals():
            _implementation.__dict__[name] = globals()[name]
    _implementation._default_probe = _default_probe
    _implementation._features = _features
    _implementation._candidate_and_evidence = _candidate_and_evidence
    _implementation._company_candidate_and_evidence = (
        _company_candidate_and_evidence
    )
    _implementation.create_alpaca_paper_client = create_alpaca_paper_client
    _implementation.SECEdgarProvider = SECEdgarProvider


def _default_probe(
    universe,
    decision_as_of,
    *,
    required_holding_symbols=(),
):
    """Collect every scheduled instrument without retaining all raw history in RAM."""

    _synchronize_runtime_bindings()
    return collect_spooled_paper_evidence(
        universe,
        decision_as_of,
        create_alpaca_client=create_alpaca_paper_client,
        sec_provider_factory=SECEdgarProvider,
        fred_provider_factory=FREDProvider,
        direct_market_client_type=DirectGlobalMarketClient,
        direct_market_universe_type=DirectGlobalMarketUniverse,
        filing_query_type=FilingQuery,
        candidate_asset_class=CandidateAssetClass,
        instrument_evaluation_scheduled=instrument_evaluation_scheduled,
        history_days=_HISTORY_DAYS,
        required_holding_symbols=required_holding_symbols,
    )


def collect_paper_evidence(*args, **kwargs):
    _synchronize_runtime_bindings()
    return _ORIGINAL_COLLECT_PAPER_EVIDENCE(*args, **kwargs)


def _features(symbol, raw_bars, quote, **kwargs):
    """Build standard features and one bounded point-in-time flow observation."""

    _synchronize_runtime_bindings()
    features = _ORIGINAL_FEATURES(symbol, raw_bars, quote, **kwargs)
    as_of = kwargs.get("as_of")
    if as_of is None:
        raise ProductionPaperEvidenceError(
            f"predictive flow evidence lacks an as_of boundary for {symbol}"
        )
    rows = _implementation._bar_rows(symbol, raw_bars, as_of=as_of)
    observation = CapitalFlowEngine.observe(
        symbol=symbol,
        as_of=as_of,
        rows=rows,
        evidence_identifiers=features.evidence_identifiers,
    )
    _flow_registry()[_flow_key(symbol, as_of)] = observation
    return features


def _predictive_candidate_and_evidence(candidate, evidence, features):
    observation = _flow_registry().get(
        _flow_key(features.symbol, candidate.as_of)
    )
    if observation is None:
        if _production_build_active():
            raise ProductionPaperEvidenceError(
                f"point-in-time capital-flow evidence is unavailable for {features.symbol}"
            )
        observation = _compatibility_flow_observation(features, candidate.as_of)
    predictive = build_predictive_market_intelligence(
        candidate=candidate,
        features=features,
        flow_observation=observation,
        market=evidence.market,
        existing_forward_intelligence=evidence.forward_intelligence,
    )
    persisted_forward = predictive.forward_intelligence
    if len(persisted_forward.model_versions) > 1:
        composite_version = "forward-bundle[" + "|".join(
            persisted_forward.model_versions
        ) + "]"
        persisted_forward = replace(
            persisted_forward,
            model_versions=(composite_version,),
        )
    lineage = replace(
        evidence.lineage,
        evidence_identifiers=tuple(
            dict.fromkeys(
                (
                    *evidence.lineage.evidence_identifiers,
                    *predictive.evidence_identifiers,
                )
            )
        ),
        model_versions=tuple(
            dict.fromkeys(
                (
                    *evidence.lineage.model_versions,
                    *predictive.model_versions,
                )
            )
        ),
    )
    enriched_evidence = replace(
        evidence,
        market=predictive.market,
        forward_intelligence=persisted_forward,
        lineage=lineage,
    )
    enriched_candidate = replace(
        candidate,
        primary_catalysts=tuple(
            dict.fromkeys(
                (
                    *candidate.primary_catalysts,
                    f"Expected market surprise is {predictive.expectations.expected_surprise:+.2%} with flow state {predictive.flow.state.value}",
                )
            )
        ),
        key_risks=tuple(
            dict.fromkeys(
                (
                    *candidate.key_risks,
                    f"Capital-flow reversal risk is {predictive.flow.reversal_risk:.0%}",
                    f"Estimated priced-in score is {predictive.expectations.priced_in_score:.0%}",
                )
            )
        ),
        supporting_evidence=tuple(
            dict.fromkeys(
                (
                    *candidate.supporting_evidence,
                    *predictive.flow.diagnostics,
                    *predictive.expectations.diagnostics,
                )
            )
        ),
        contradictory_evidence=tuple(
            dict.fromkeys(
                (
                    *candidate.contradictory_evidence,
                    "Capital-flow evidence is currently a price-and-volume proxy rather than complete institutional ownership flow",
                )
            )
        ),
        monitoring_indicators=tuple(
            dict.fromkeys(
                (
                    *candidate.monitoring_indicators,
                    "signed_dollar_flow",
                    "volume_impulse",
                    "flow_persistence",
                    "flow_crowding",
                    "expected_market_surprise",
                    "priced_in_score",
                )
            )
        ),
        evidence_identifiers=tuple(
            dict.fromkeys(
                (
                    *candidate.evidence_identifiers,
                    *predictive.evidence_identifiers,
                )
            )
        ),
        model_versions=tuple(
            dict.fromkeys(
                (
                    *candidate.model_versions,
                    *(version for _name, version in predictive.model_versions),
                )
            )
        ),
    )
    return enriched_candidate, enriched_evidence


def _candidate_and_evidence(instrument, features, *args, **kwargs):
    _synchronize_runtime_bindings()
    candidate, evidence = _ORIGINAL_CANDIDATE_AND_EVIDENCE(
        instrument,
        features,
        *args,
        **kwargs,
    )
    uses_derivatives = (
        instrument.uses_derivatives
        or instrument.economic_exposure in _DERIVATIVE_WRAPPER_EXPOSURES
    )
    if uses_derivatives and not candidate.instrument.uses_derivatives:
        candidate = replace(
            candidate,
            instrument=replace(candidate.instrument, uses_derivatives=True),
        )
    return _predictive_candidate_and_evidence(candidate, evidence, features)


def _company_candidate_and_evidence(instrument, features, *args, **kwargs):
    _synchronize_runtime_bindings()
    candidate, evidence = _ORIGINAL_COMPANY_CANDIDATE_AND_EVIDENCE(
        instrument,
        features,
        *args,
        **kwargs,
    )
    return _predictive_candidate_and_evidence(candidate, evidence, features)


def build_paper_evidence(*args, **kwargs):
    _synchronize_runtime_bindings()
    _FLOW_STATE.observations = {}
    _FLOW_STATE.production_build = True
    try:
        return _ORIGINAL_BUILD_PAPER_EVIDENCE(*args, **kwargs)
    finally:
        _FLOW_STATE.production_build = False
        _FLOW_STATE.observations = {}


_implementation._default_probe = _default_probe
_implementation._features = _features
_implementation._candidate_and_evidence = _candidate_and_evidence
_implementation._company_candidate_and_evidence = _company_candidate_and_evidence
_implementation.create_alpaca_paper_client = create_alpaca_paper_client
_implementation.SECEdgarProvider = SECEdgarProvider
__all__ = tuple(
    dict.fromkeys(
        (*getattr(_implementation, "__all__", ()), "close_spooled_paper_evidence")
    )
)
