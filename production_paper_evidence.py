"""Governed facade preserving paper-evidence compatibility and risk lineage.

The complete implementation remains in ``production_paper_evidence_impl``. This
facade preserves the historical module-level monkeypatch boundary used by tests and
operations while restoring derivative-risk truth, streaming full provider evidence
through a disk-backed cycle spool, and enriching every governed candidate with
point-in-time capital-flow, certified forward research, Phase-5 intelligence,
governed event transmission, and global opportunity intelligence.
"""

from __future__ import annotations

import threading
from dataclasses import replace

import intelligence.predictive_market as _predictive_market
import production_paper_evidence_impl as _implementation
from governance.decision_readiness import CandidateDecisionReadinessPolicy
from intelligence.global_opportunity import (
    BullMarketStage,
    CanonicalExposureGraph,
    GlobalBullMarketRadarEngine,
    PersistentOpportunitySweep,
    RadarObservation,
)
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
from providers.event_forward import (
    build_configured_event_forward_provider,
    build_governed_event_forward,
)
from providers.forward_intelligence import (
    build_configured_forward_intelligence_provider,
)
from providers.forward_research import build_configured_forward_research_provider
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


def _feature_registry() -> dict[tuple[str, str], object]:
    values = getattr(_FLOW_STATE, "features", None)
    if values is None:
        values = {}
        _FLOW_STATE.features = values
    return values


def _flow_key(symbol: str, as_of) -> tuple[str, str]:
    return str(symbol).upper(), as_of.isoformat()


def _production_build_active() -> bool:
    return bool(getattr(_FLOW_STATE, "production_build", False))


def _collapse_forward_versions(bundle):
    if bundle is None or len(bundle.model_versions) <= 1:
        return bundle
    return replace(
        bundle,
        model_versions=("forward-bundle[" + "|".join(bundle.model_versions) + "]",),
    )


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
    """Build standard features and bounded point-in-time predictive observations."""

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
    key = _flow_key(symbol, as_of)
    _flow_registry()[key] = observation
    _feature_registry()[key] = features
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

    existing_forward = evidence.forward_intelligence
    forward_intelligence_provider = getattr(
        _FLOW_STATE, "forward_intelligence_provider", None
    )
    if forward_intelligence_provider is not None:
        phase5_forward = forward_intelligence_provider.fetch(candidate)
        if phase5_forward is not None:
            existing_forward = reconcile_forward_intelligence(
                existing_forward,
                phase5_forward,
            )

    forward_research_provider = getattr(
        _FLOW_STATE, "forward_research_provider", None
    )
    research_evidence = (
        None
        if forward_research_provider is None
        else forward_research_provider.fetch(candidate)
    )
    predictive = build_predictive_market_intelligence(
        candidate=candidate,
        features=features,
        flow_observation=observation,
        market=evidence.market,
        existing_forward_intelligence=existing_forward,
        research_evidence=research_evidence,
    )
    persisted_forward = _collapse_forward_versions(
        predictive.forward_intelligence
    )
    existing_forward_ids = (
        () if existing_forward is None else existing_forward.evidence_identifiers
    )
    existing_forward_versions = (
        () if existing_forward is None else existing_forward.model_versions
    )
    phase5_lineage_versions = (
        (("phase5_forward", "|".join(existing_forward_versions)),)
        if existing_forward_versions
        else ()
    )
    lineage = replace(
        evidence.lineage,
        evidence_identifiers=tuple(
            dict.fromkeys(
                (
                    *evidence.lineage.evidence_identifiers,
                    *existing_forward_ids,
                    *predictive.evidence_identifiers,
                )
            )
        ),
        model_versions=tuple(
            dict.fromkeys(
                (
                    *evidence.lineage.model_versions,
                    *phase5_lineage_versions,
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
                    *existing_forward_ids,
                    *predictive.evidence_identifiers,
                )
            )
        ),
        model_versions=tuple(
            dict.fromkeys(
                (
                    *candidate.model_versions,
                    *existing_forward_versions,
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


def _enrich_global_opportunity_result(result, *, universe, decision_as_of):
    """Add global leadership and certified event evidence without changing authority."""

    candidates_by_symbol = {
        item.instrument.symbol.upper(): item for item in result.candidates
    }
    instrument_by_symbol = {
        item.symbol.upper(): item for item in universe.instruments
    }
    observations = []
    for symbol, candidate in candidates_by_symbol.items():
        features = _feature_registry().get(_flow_key(symbol, decision_as_of))
        instrument = instrument_by_symbol.get(symbol)
        if features is None or instrument is None:
            continue
        observations.append(
            RadarObservation(
                candidate_identifier=candidate.identifier,
                instrument_identifier=candidate.instrument.instrument_id,
                symbol=symbol,
                as_of=candidate.as_of,
                asset_class=candidate.instrument.asset_class,
                economic_exposure=instrument.economic_exposure,
                country_code=instrument.country_code,
                currency=instrument.currency,
                venue=instrument.venue,
                one_month_return=features.one_month_return,
                three_month_return=features.three_month_return,
                six_month_return=features.six_month_return,
                twelve_month_return=features.twelve_month_return,
                annualized_volatility=features.annualized_volatility,
                maximum_drawdown=features.maximum_drawdown,
                liquidity_score=features.liquidity_score,
                evidence_identifiers=features.evidence_identifiers,
            )
        )
    if not observations:
        return result

    radar_engine = GlobalBullMarketRadarEngine()
    radar = radar_engine.scan(tuple(observations))
    forward_intelligence_provider = getattr(
        _FLOW_STATE, "forward_intelligence_provider", None
    )
    graph = (
        CanonicalExposureGraph.from_instruments(
            universe.instruments,
            as_of=decision_as_of,
        )
        if forward_intelligence_provider is None
        else forward_intelligence_provider.exposure_graph(
            universe.instruments,
            as_of=decision_as_of,
        )
    )
    sweep_engine = PersistentOpportunitySweep()
    sweep = sweep_engine.run(radar, graph)
    assessments = radar.by_candidate
    nominations = sweep.by_candidate

    event_provider = getattr(_FLOW_STATE, "event_forward_provider", None)
    event_result = None
    if event_provider is not None:
        features_by_symbol = {
            symbol: _feature_registry()[_flow_key(symbol, decision_as_of)]
            for symbol in candidates_by_symbol
            if _flow_key(symbol, decision_as_of) in _feature_registry()
        }
        event_result = build_governed_event_forward(
            provider=event_provider,
            graph=graph,
            candidates=tuple(result.candidates),
            features_by_symbol=features_by_symbol,
            as_of=decision_as_of,
        )
    event_by_candidate = {} if event_result is None else event_result.by_candidate

    evidence_by_candidate = {
        item.candidate_identifier: item for item in result.candidate_evidence
    }
    enriched_candidates = []
    enriched_evidence = []

    for candidate in result.candidates:
        assessment = assessments.get(candidate.identifier)
        evidence = evidence_by_candidate[candidate.identifier]
        if assessment is None:
            enriched_candidates.append(candidate)
            enriched_evidence.append(evidence)
            continue

        graph_evidence_identifier = (
            f"governed-universe:{candidate.instrument.instrument_id}"
        )
        event_bundle = event_by_candidate.get(candidate.identifier)
        event_ids = () if event_bundle is None else event_bundle.evidence_identifiers
        local_evidence_ids = tuple(
            dict.fromkeys(
                (
                    *assessment.evidence_identifiers,
                    graph_evidence_identifier,
                    *event_ids,
                )
            )
        )
        market_risks = list(evidence.market.risks)
        if assessment.stage is BullMarketStage.CROWDED_FRAGILE:
            market_risks.append(
                "Global leadership is strong but the price/volatility crowding proxy is elevated."
            )
        elif assessment.stage is BullMarketStage.DETERIORATING:
            market_risks.append(
                "Global radar indicates deteriorating leadership despite longer-horizon support."
            )
        market = replace(
            evidence.market,
            breadth=round(assessment.breadth * 2.0 - 1.0, 8),
            evidence=tuple(
                dict.fromkeys(
                    (
                        *evidence.market.evidence,
                        f"Global opportunity rank={assessment.rank}; score={assessment.score:.0%}; stage={assessment.stage.value}",
                        f"Cross-sectional relative strength={assessment.relative_strength:.0%}; breadth={assessment.breadth:.0%}",
                        f"Leadership acceleration={assessment.acceleration:+.2f}; durability={assessment.durability:.0%}",
                    )
                )
            ),
            risks=tuple(dict.fromkeys(market_risks)),
            evidence_identifiers=tuple(
                dict.fromkeys(
                    (*evidence.market.evidence_identifiers, *local_evidence_ids)
                )
            ),
        )

        nomination = nominations.get(candidate.identifier)
        forward_intelligence = evidence.forward_intelligence
        if nomination is not None:
            safe_nomination = replace(
                nomination,
                evidence_identifiers=local_evidence_ids,
            )
            radar_bundle = sweep_engine.forward_bundle(
                safe_nomination,
                assessment,
            )
            forward_intelligence = reconcile_forward_intelligence(
                forward_intelligence,
                radar_bundle,
            )
        if event_bundle is not None:
            forward_intelligence = reconcile_forward_intelligence(
                forward_intelligence,
                event_bundle,
            )
        forward_intelligence = _collapse_forward_versions(forward_intelligence)

        lineage_versions = [
            *evidence.lineage.model_versions,
            ("global_opportunity_radar", radar_engine.version),
            ("persistent_opportunity_sweep", sweep_engine.version),
            ("canonical_exposure_graph", graph.version),
        ]
        if event_bundle is not None:
            lineage_versions.append(
                ("governed_event_forward", "|".join(event_bundle.model_versions))
            )
        lineage = replace(
            evidence.lineage,
            evidence_identifiers=tuple(
                dict.fromkeys(
                    (*evidence.lineage.evidence_identifiers, *local_evidence_ids)
                )
            ),
            model_versions=tuple(dict.fromkeys(lineage_versions)),
        )
        stage_evidence = (
            f"Global radar stage={assessment.stage.value}; rank={assessment.rank}; score={assessment.score:.0%}; "
            f"relative strength={assessment.relative_strength:.0%}; breadth={assessment.breadth:.0%}"
        )
        candidate_risks = list(candidate.key_risks)
        candidate_contradictions = list(candidate.contradictory_evidence)
        if assessment.stage is BullMarketStage.CROWDED_FRAGILE:
            candidate_risks.append(
                f"Global leadership crowding proxy is {assessment.trend_crowding_proxy:.0%}; trend reversal risk requires monitoring."
            )
        if assessment.stage in {BullMarketStage.DETERIORATING, BullMarketStage.BEAR}:
            candidate_contradictions.append(
                f"Global opportunity radar classifies current leadership as {assessment.stage.value}."
            )
        monitoring = [
            *candidate.monitoring_indicators,
            "global_opportunity_rank",
            "global_bull_market_stage",
            "cross_sectional_relative_strength",
            "cross_sectional_breadth",
            "leadership_acceleration",
        ]
        model_versions = [
            *candidate.model_versions,
            radar_engine.version,
            sweep_engine.version,
            graph.version,
        ]
        supporting = [*candidate.supporting_evidence, stage_evidence]
        if event_bundle is not None:
            monitoring.append("governed_event_forward_context")
            model_versions.extend(event_bundle.model_versions)
            supporting.append(
                "Certified decision-information passed event quality, causal transmission, and market-confirmation gates for this candidate."
            )
        enriched_candidate = replace(
            candidate,
            supporting_evidence=tuple(dict.fromkeys(supporting)),
            key_risks=tuple(dict.fromkeys(candidate_risks)),
            contradictory_evidence=tuple(dict.fromkeys(candidate_contradictions)),
            monitoring_indicators=tuple(dict.fromkeys(monitoring)),
            evidence_identifiers=tuple(
                dict.fromkeys((*candidate.evidence_identifiers, *local_evidence_ids))
            ),
            model_versions=tuple(dict.fromkeys(model_versions)),
        )
        enriched_governed = replace(
            evidence,
            market=market,
            forward_intelligence=forward_intelligence,
            lineage=lineage,
        )
        enriched_candidates.append(enriched_candidate)
        enriched_evidence.append(enriched_governed)

    return replace(
        result,
        candidates=tuple(enriched_candidates),
        candidate_evidence=tuple(enriched_evidence),
    )


def build_paper_evidence(*args, **kwargs):
    _synchronize_runtime_bindings()
    _FLOW_STATE.observations = {}
    _FLOW_STATE.features = {}
    _FLOW_STATE.forward_research_provider = (
        build_configured_forward_research_provider()
    )
    _FLOW_STATE.forward_intelligence_provider = (
        build_configured_forward_intelligence_provider()
    )
    _FLOW_STATE.event_forward_provider = build_configured_event_forward_provider()
    _FLOW_STATE.production_build = True
    try:
        result = _ORIGINAL_BUILD_PAPER_EVIDENCE(*args, **kwargs)
        universe = kwargs.get("universe")
        decision_as_of = kwargs.get("decision_as_of")
        if universe is None or decision_as_of is None:
            return result
        enriched = _enrich_global_opportunity_result(
            result,
            universe=universe,
            decision_as_of=decision_as_of,
        )
        return CandidateDecisionReadinessPolicy().filter_paper_evidence_result(
            enriched
        )
    finally:
        _FLOW_STATE.production_build = False
        _FLOW_STATE.observations = {}
        _FLOW_STATE.features = {}
        _FLOW_STATE.forward_research_provider = None
        _FLOW_STATE.forward_intelligence_provider = None
        _FLOW_STATE.event_forward_provider = None


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
