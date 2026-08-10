"""Governed decision-information to event/market forward-intelligence bridge.

Only canonical ``DecisionInformationRecord`` values enter this bridge. Explicitly
configured licensed datasets remain preferred. When no licensed binding is present,
a conservative subset of the already-collected official/regulatory public record set
may supply supporting evidence through ``PublicDecisionInformationProvider``.
Educational headlines remain outside decision evidence. Every event must still pass
source quality, novelty/materiality, causal-transmission, exposure, and
market-confirmation gates before it can enrich an existing candidate. The bridge
cannot create candidates or authorize capital.

The result also retains the exact governed ``EventMarketAssessment`` objects and their
canonical candidate-exposure links as research lineage. That lineage is read-only and
exists so the causal hypotheses the CIO actually saw can later be resolved and
calibrated without reconstructing them from hindsight.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from statistics import fmean

from data.decision_information import DecisionInformationProvider
from intelligence.event_market_forward import (
    EventMarketAssessment,
    EventToForwardEngine,
    MarketObservation,
)
from intelligence.event_quality import assess_event_clusters, semantic_event_key
from intelligence.forward import ForwardIntelligenceBundle
from intelligence.global_opportunity import CanonicalExposureGraph
from providers.configured_information import (
    build_configured_decision_information_provider,
)
from providers.public_decision_information import (
    build_public_decision_information_provider,
)


@dataclass(frozen=True, slots=True)
class GovernedEventForwardResult:
    bundles: tuple[ForwardIntelligenceBundle, ...]
    assessment_identifiers: tuple[str, ...]
    hypothesis_identifiers: tuple[str, ...]
    diagnostics: tuple[str, ...]
    assessments: tuple[EventMarketAssessment, ...] = ()
    candidate_exposure_links: tuple[tuple[str, str, str], ...] = ()
    authorizes_capital: bool = False
    schema_version: str = "governed-event-forward-result.v3-causal-lineage"

    def __post_init__(self) -> None:
        if self.authorizes_capital:
            raise ValueError("event-forward research lineage cannot authorize capital")
        assessment_ids = tuple(item.identifier for item in self.assessments)
        if len(assessment_ids) != len(set(assessment_ids)):
            raise ValueError("event-forward assessments must be unique")
        if self.assessments and set(assessment_ids) != set(self.assessment_identifiers):
            raise ValueError("assessment identifiers must match retained assessments")
        for assessment_identifier, target_identifier, candidate_identifier in self.candidate_exposure_links:
            if not all(str(value).strip() for value in (assessment_identifier, target_identifier, candidate_identifier)):
                raise ValueError("candidate exposure links cannot contain empty values")
            if self.assessments and assessment_identifier not in set(assessment_ids):
                raise ValueError("candidate exposure link references an unknown assessment")

    @property
    def by_candidate(self) -> dict[str, ForwardIntelligenceBundle]:
        return {item.candidate_identifier: item for item in self.bundles}


def _lookback_days() -> int:
    raw = os.getenv("CAPITAL_INTELLIGENCE_DECISION_INFORMATION_LOOKBACK_DAYS", "7")
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError("decision-information lookback days must be an integer") from error
    if not 1 <= value <= 30:
        raise ValueError("decision-information lookback days must be between 1 and 30")
    return value


def _confirmation(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    # The event-quality gate defines 2% as full market confirmation. We retain
    # direction for EventToForwardEngine and use absolute magnitude only for the
    # prior cluster admission gate.
    return round(min(1.0, max(abs(item) for item in values) / 0.02), 8)


def build_governed_event_forward(
    *,
    provider: DecisionInformationProvider,
    graph: CanonicalExposureGraph,
    candidates: tuple[object, ...],
    features_by_symbol: dict[str, object],
    as_of,
) -> GovernedEventForwardResult:
    records = provider.records(
        start_at=as_of - timedelta(days=_lookback_days()),
        as_of=as_of,
    )
    if not records:
        return GovernedEventForwardResult(
            (),
            (),
            (),
            ("No certified current decision-information records were available.",),
        )

    candidate_by_instrument = {
        str(item.instrument.instrument_id): item for item in candidates
    }
    candidate_by_symbol = {
        str(item.instrument.symbol).upper(): item for item in candidates
    }

    confirmation_map: dict[str, float] = {}
    record_payloads = []
    for record in records:
        payload = record.to_dict()
        record_payloads.append(payload)
        values: list[float] = []
        for raw in (*record.instruments, *record.entities, *record.sectors):
            symbol = str(raw).upper()
            if symbol in features_by_symbol:
                values.append(float(features_by_symbol[symbol].one_month_return))
            for exposure in graph.research_exposures(str(raw)):
                feature = features_by_symbol.get(exposure.symbol.upper())
                if feature is not None:
                    values.append(float(feature.one_month_return))
        confirmation_map[semantic_event_key(payload)] = _confirmation(tuple(values))

    clusters = assess_event_clusters(
        record_payloads,
        market_confirmation=confirmation_map,
    )
    records_by_identifier = {item.identifier: item for item in records}
    engine = EventToForwardEngine()
    bundle_by_candidate: dict[str, ForwardIntelligenceBundle] = {}
    assessments: list[EventMarketAssessment] = []
    assessment_ids: list[str] = []
    hypothesis_ids: list[str] = []
    candidate_exposure_links: list[tuple[str, str, str]] = []

    for cluster, _representative_payload in clusters:
        record = records_by_identifier.get(cluster.representative_identifier)
        if record is None or not cluster.eligible_for_analysis:
            continue
        drivers = engine.catalog.match(
            record,
            minimum_score=engine.policy.minimum_rule_score,
        )
        target_identifiers = tuple(
            dict.fromkeys(
                transmission.target_identifier
                for driver in drivers
                for transmission in driver.transmissions
            )
        )
        observations: list[MarketObservation] = []
        candidate_exposure_map: dict[str, tuple[str, ...]] = {}
        for target in target_identifiers:
            exposures = graph.research_exposures(target)
            candidate_ids: list[str] = []
            returns: list[float] = []
            evidence_ids: list[str] = []
            for exposure in exposures:
                candidate = candidate_by_instrument.get(exposure.instrument_identifier)
                if candidate is None:
                    candidate = candidate_by_symbol.get(exposure.symbol.upper())
                feature = features_by_symbol.get(exposure.symbol.upper())
                if candidate is None or feature is None:
                    continue
                candidate_ids.append(candidate.identifier)
                returns.append(float(feature.one_month_return))
                evidence_ids.extend(exposure.evidence_identifiers)
                evidence_ids.extend(feature.evidence_identifiers)
            if candidate_ids:
                candidate_exposure_map[target] = tuple(dict.fromkeys(candidate_ids))
            if returns:
                observations.append(
                    MarketObservation(
                        identifier=f"event-confirmation:{cluster.identifier}:{target}",
                        exposure_identifier=target,
                        observed_at=as_of,
                        return_change=round(fmean(returns), 8),
                        evidence_identifiers=tuple(dict.fromkeys(evidence_ids)),
                    )
                )
        assessment = engine.assess(
            record,
            event_cluster=cluster,
            observations=tuple(observations),
            assessed_at=as_of,
        )
        assessments.append(assessment)
        assessment_ids.append(assessment.identifier)
        for target_identifier, candidate_identifiers in candidate_exposure_map.items():
            candidate_exposure_links.extend(
                (
                    assessment.identifier,
                    target_identifier,
                    candidate_identifier,
                )
                for candidate_identifier in candidate_identifiers
            )
        hypotheses = graph.discover_event_opportunities(assessment)
        hypothesis_ids.extend(item.identifier for item in hypotheses)
        for bundle in engine.build_forward_bundles(
            assessment,
            candidate_exposure_map=candidate_exposure_map,
        ):
            existing = bundle_by_candidate.get(bundle.candidate_identifier)
            if existing is None:
                bundle_by_candidate[bundle.candidate_identifier] = bundle
                continue
            # Same-candidate events remain distinct evidence signals. Use the
            # canonical predictive merge helper to preserve every source id while
            # deduplicating scenario labels.
            from intelligence.predictive_scenario_merge import (
                reconcile_forward_intelligence,
            )

            bundle_by_candidate[bundle.candidate_identifier] = (
                reconcile_forward_intelligence(existing, bundle)
            )

    return GovernedEventForwardResult(
        bundles=tuple(
            bundle_by_candidate[key] for key in sorted(bundle_by_candidate)
        ),
        assessment_identifiers=tuple(dict.fromkeys(assessment_ids)),
        hypothesis_identifiers=tuple(dict.fromkeys(hypothesis_ids)),
        diagnostics=(
            f"Evaluated {len(records)} certified decision-information records across {len(clusters)} event clusters.",
            f"Escalated forward evidence to {len(bundle_by_candidate)} already-governed candidates.",
            "Public records enter only through the strict public-decision-information policy; educational headlines remain outside investment authority.",
        ),
        assessments=tuple(assessments),
        candidate_exposure_links=tuple(dict.fromkeys(candidate_exposure_links)),
    )


def build_configured_event_forward_provider() -> DecisionInformationProvider | None:
    """Prefer licensed configured evidence; otherwise use strict public evidence.

    The fallback is intentionally not equivalent to a licensed newswire. It admits
    only records satisfying ``PublicDecisionInformationPolicy`` and remains
    supporting evidence subject to all downstream event-forward gates.
    """

    if os.getenv(
        "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_DATASET_BINDING",
        "",
    ).strip():
        return build_configured_decision_information_provider()
    return build_public_decision_information_provider()


__all__ = [
    "GovernedEventForwardResult",
    "build_configured_event_forward_provider",
    "build_governed_event_forward",
]
