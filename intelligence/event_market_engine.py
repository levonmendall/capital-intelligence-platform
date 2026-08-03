"""General event-to-market engine orchestration and persistence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from data.decision_information import (
    CurrentEventPortfolioAnalyzer,
    DecisionInformationRecord,
    InformationQualityState,
)
from intelligence.event_market_models import (
    CandidateEventMarketEvidence,
    EventCoverageState,
    EventDriver,
    EventMarketAssessment,
    EventMarketDomain,
    EventMarketPolicy,
    EventMarketState,
    EventRule,
    GovernedEventMarketResult,
    MarketObservation,
    MarketTransmission,
    TransmissionDirection,
    _aware,
    _record_text,
    _ratio,
    _text,
    _texts,
    _unique,
)


def _default_event_rules() -> tuple[EventRule, ...]:
    from intelligence.event_market_rules import default_event_rules
    return default_event_rules()

class EventRuleCatalog:
    """Composable versioned rule catalog for recurring major headline families."""

    def __init__(
        self,
        rules: tuple[EventRule, ...] | None = None,
        *,
        version: str = "event-market-rules.2026-08-02.v2",
    ) -> None:
        self.version = _text(version, field_name="version")
        self.rules = rules or _default_event_rules()
        if not isinstance(self.rules, tuple) or not all(
            isinstance(item, EventRule) for item in self.rules
        ):
            raise TypeError("rules must contain EventRule values")
        identifiers = tuple(item.identifier for item in self.rules)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("event rule identifiers must be unique")

    def match(
        self,
        record: DecisionInformationRecord,
        *,
        minimum_score: float,
    ) -> tuple[EventDriver, ...]:
        text = _record_text(record)
        drivers = []
        for rule in self.rules:
            score = rule.match_score(record, text)
            if score < minimum_score:
                continue
            drivers.append(
                EventDriver(
                    rule_identifier=rule.identifier,
                    domain=rule.domain,
                    state=rule.state,
                    confidence=score,
                    causal_chain=rule.causal_chain,
                    transmissions=rule.transmissions,
                    alternatives=rule.alternatives,
                )
            )
        return tuple(
            sorted(
                drivers,
                key=lambda item: (item.confidence, item.rule_identifier),
                reverse=True,
            )
        )


class EventToMarketEngine:
    """General major-headline causal mapping with market confirmation."""

    _CHANNEL_TARGETS: Mapping[str, tuple[str, ...]] = {
        "growth": ("broad_equities", "cyclical_equities", "credit"),
        "inflation": ("inflation_expectations", "bond_prices", "growth_equities"),
        "policy": ("policy_rate_expectations", "bond_prices", "us_dollar"),
        "liquidity": ("liquidity", "credit", "volatility"),
        "discount_rate": ("bond_prices", "growth_equities", "real_estate"),
        "earnings": ("affected_issuer", "affected_sector", "issuer_credit"),
        "credit": ("credit", "financials", "treasuries"),
        "supply": ("affected_commodity", "commodity_producers", "commodity_consumers"),
        "demand": ("cyclical_equities", "affected_commodity", "credit"),
        "commodity": ("affected_commodity", "commodity_producers", "commodity_consumers"),
        "currency": ("local_currency", "local_exporters", "local_importers"),
        "volatility": ("volatility", "broad_equities"),
        "regulation": ("affected_issuer", "affected_sector"),
        "geopolitical": ("geopolitical_risk", "affected_region", "volatility"),
        "operational": ("affected_issuer", "affected_customers", "supply_chain"),
        "cyber": ("affected_issuer", "affected_customers", "cybersecurity_vendors"),
        "climate_weather": ("affected_region", "insurers", "affected_commodity"),
        "positioning": ("liquidity", "volatility"),
        "sentiment": ("affected_issuer", "affected_sector"),
        "counterparty": ("credit", "financials", "volatility"),
    }

    def __init__(
        self,
        policy: EventMarketPolicy | None = None,
        *,
        catalog: EventRuleCatalog | None = None,
    ) -> None:
        self.policy = policy or EventMarketPolicy()
        self.catalog = catalog or EventRuleCatalog()

    def assess(
        self,
        record: DecisionInformationRecord,
        *,
        event_cluster: object,
        observations: tuple[MarketObservation, ...],
        assessed_at: datetime,
        owned_instrument_identifiers: tuple[str, ...] = (),
        exposure_map: Mapping[str, Sequence[str]] | None = None,
    ) -> EventMarketAssessment:
        if not isinstance(record, DecisionInformationRecord):
            raise TypeError("record must be DecisionInformationRecord")
        timestamp = _aware(assessed_at, field_name="assessed_at")
        record.require_available_to(timestamp)
        if not isinstance(observations, tuple) or not all(
            isinstance(item, MarketObservation) for item in observations
        ):
            raise TypeError("observations must contain MarketObservation values")
        if any(item.observed_at > timestamp for item in observations):
            raise ValueError("market observations cannot be future-known")

        cluster_identifier = _text(
            getattr(event_cluster, "identifier", ""),
            field_name="event_cluster.identifier",
        )
        cluster_quality = _ratio(
            getattr(event_cluster, "quality_score", 0.0),
            field_name="event_cluster.quality_score",
        )
        cluster_eligible = bool(getattr(event_cluster, "eligible_for_cio_context", False))
        cluster_evidence = tuple(
            str(value)
            for value in getattr(event_cluster, "source_identifiers", ())
            if str(value).strip()
        )
        base_evidence = _unique(
            (
                record.identifier,
                record.provenance.source_identifier,
                *record.corroborating_source_identifiers,
                *cluster_evidence,
            )
        )

        drivers = self.catalog.match(
            record,
            minimum_score=self.policy.minimum_rule_score,
        )
        major_headline = (
            record.materiality >= self.policy.minimum_major_headline_materiality
            and cluster_quality >= self.policy.minimum_cluster_quality
        )
        if drivers:
            primary = drivers[0]
            state = primary.state
            domains = tuple(dict.fromkeys(item.domain for item in drivers))
            causal_chain = _unique(
                step for driver in drivers for step in driver.causal_chain
            )
            alternatives = _unique(
                item for driver in drivers for item in driver.alternatives
            )
            coverage_state = EventCoverageState.MAPPED
            unresolved_questions: tuple[str, ...] = ()
            predicted = self._aggregate_transmissions(drivers)
        else:
            state = (
                EventMarketState.UNRESOLVED_MAJOR_EVENT
                if major_headline
                else EventMarketState.UNKNOWN
            )
            domains = self._infer_domains(record)
            causal_chain = (
                "A material event was detected, but the current evidence does not establish a defensible directional causal chain.",
                "The engine preserves the affected channels and requests causal review rather than inventing a market conclusion.",
            )
            alternatives = (
                "The event may operate through an unfamiliar mechanism not represented in the current rule catalog.",
                "The headline may omit the facts needed to distinguish direction, magnitude, timing, or affected exposures.",
            )
            coverage_state = EventCoverageState.UNRESOLVED
            unresolved_questions = (
                "What economic variable, cash flow, risk premium, or physical constraint changed?",
                "Which entities, instruments, sectors, regions, or counterparties are directly exposed?",
                "What contemporaneous market evidence confirms the proposed direction?",
            )
            predicted = self._fallback_transmissions(record)

        transmissions, confirmation, confirmation_coverage, contradictions = self._confirm(
            predicted,
            observations,
            base_evidence=base_evidence,
        )
        driver_confidence = (
            sum(item.confidence for item in drivers) / len(drivers)
            if drivers
            else 0.0
        )
        confidence = round(
            min(
                1.0,
                0.30 * record.evidence_strength
                + 0.25 * cluster_quality
                + 0.25 * driver_confidence
                + 0.20 * confirmation,
            ),
            8,
        )
        mapping = exposure_map or {}
        owned = set(
            _texts(
                owned_instrument_identifiers,
                field_name="owned_instrument_identifiers",
            )
        )
        affected = {
            value
            for transmission in transmissions
            for value in mapping.get(transmission.target_identifier, ())
            if value in owned
        }
        quality_blocked = record.provenance.quality_state in {
            InformationQualityState.DISPUTED,
            InformationQualityState.UNVERIFIED,
            InformationQualityState.MISSING,
        }
        material_directional = any(
            item.direction in {TransmissionDirection.POSITIVE, TransmissionDirection.NEGATIVE}
            and item.magnitude >= 0.25
            for item in transmissions
        )
        requires_causal_review = (
            major_headline
            and (
                not drivers
                or bool(contradictions)
                or confirmation_coverage < self.policy.minimum_confirmation_coverage
            )
        )
        if drivers and any(
            item.direction is TransmissionDirection.MIXED for item in transmissions
        ):
            coverage_state = EventCoverageState.PARTIAL
        eligible = (
            bool(drivers)
            and material_directional
            and not quality_blocked
            and cluster_eligible
            and cluster_quality >= self.policy.minimum_cluster_quality
            and record.evidence_strength >= self.policy.minimum_record_evidence_strength
            and confirmation >= self.policy.minimum_market_confirmation
            and confirmation_coverage >= self.policy.minimum_confirmation_coverage
            and confidence >= self.policy.minimum_assessment_confidence
        )
        material = "|".join(
            (
                record.identifier,
                cluster_identifier,
                state.value,
                self.catalog.version,
                *(item.rule_identifier for item in drivers),
                *(item.identifier for item in observations),
            )
        )
        identifier = "event-market:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        evidence_identifiers = _unique(
            (
                *base_evidence,
                *(item.identifier for item in observations),
                *(
                    evidence
                    for observation in observations
                    for evidence in observation.evidence_identifiers
                ),
            )
        )
        return EventMarketAssessment(
            identifier=identifier,
            information_identifier=record.identifier,
            event_cluster_identifier=cluster_identifier,
            assessed_at=timestamp,
            state=state,
            domains=domains,
            coverage_state=coverage_state,
            drivers=drivers,
            causal_chain=causal_chain,
            transmissions=transmissions,
            market_confirmation=confirmation,
            confirmation_coverage=confirmation_coverage,
            confidence=confidence,
            major_headline=major_headline,
            requires_causal_review=requires_causal_review,
            contradictory_evidence=contradictions,
            alternative_explanations=alternatives,
            unresolved_questions=unresolved_questions,
            affected_portfolio_instruments=tuple(sorted(affected)),
            evidence_identifiers=evidence_identifiers,
            eligible_for_cio_context=eligible,
            policy_version=self.policy.version,
        )

    def candidate_evidence(
        self,
        assessment: EventMarketAssessment,
        *,
        candidate_exposure_map: Mapping[str, Sequence[str]],
    ) -> tuple[CandidateEventMarketEvidence, ...]:
        if not isinstance(assessment, EventMarketAssessment):
            raise TypeError("assessment must be EventMarketAssessment")
        by_candidate: dict[str, list[MarketTransmission]] = {}
        for transmission in assessment.transmissions:
            for raw_candidate in candidate_exposure_map.get(
                transmission.target_identifier, ()
            ):
                candidate = _text(raw_candidate, field_name="candidate identifier")
                by_candidate.setdefault(candidate, []).append(transmission)
        results = []
        for candidate, transmissions in sorted(by_candidate.items()):
            weight = sum(max(item.confidence, 0.01) for item in transmissions)
            score = (
                sum(item.directional_score * max(item.confidence, 0.01) for item in transmissions)
                / weight
                if weight
                else 0.0
            )
            results.append(
                CandidateEventMarketEvidence(
                    candidate_identifier=candidate,
                    event_market_assessment_identifier=assessment.identifier,
                    as_of=assessment.assessed_at,
                    directional_score=max(-1.0, min(1.0, round(score, 8))),
                    transmissions=tuple(
                        f"{item.target_identifier}:{item.direction.value}"
                        for item in transmissions
                    ),
                    domains=assessment.domains,
                    evidence_identifiers=assessment.evidence_identifiers,
                    confidence=assessment.confidence,
                    eligible_for_specialist_context=assessment.eligible_for_cio_context,
                )
            )
        return tuple(results)

    def _infer_domains(
        self,
        record: DecisionInformationRecord,
    ) -> tuple[EventMarketDomain, ...]:
        channels = {item.value for item in record.impact_channels}
        mapping = {
            EventMarketDomain.MACRO_GROWTH: {"growth", "demand"},
            EventMarketDomain.INFLATION: {"inflation"},
            EventMarketDomain.MONETARY_POLICY: {"policy", "discount_rate"},
            EventMarketDomain.GEOPOLITICS: {"geopolitical"},
            EventMarketDomain.COMMODITY_SUPPLY: {"supply", "commodity"},
            EventMarketDomain.CORPORATE: {"earnings", "sentiment"},
            EventMarketDomain.CREDIT_FINANCIAL_STABILITY: {"credit", "counterparty"},
            EventMarketDomain.REGULATION_LEGAL: {"regulation"},
            EventMarketDomain.OPERATIONAL_CYBER: {"operational", "cyber"},
            EventMarketDomain.WEATHER_DISASTER: {"climate_weather"},
            EventMarketDomain.MARKET_LIQUIDITY: {"liquidity", "positioning", "volatility"},
            EventMarketDomain.CURRENCY: {"currency"},
        }
        domains = tuple(
            domain
            for domain, relevant in mapping.items()
            if channels.intersection(relevant)
        )
        return domains or (EventMarketDomain.UNKNOWN,)

    def _fallback_transmissions(
        self,
        record: DecisionInformationRecord,
    ) -> tuple[tuple[str, TransmissionDirection, float, str, str, tuple[str, ...]], ...]:
        channels = tuple(item.value for item in record.impact_channels)
        targets = _unique(
            target
            for channel in channels
            for target in self._CHANNEL_TARGETS.get(channel, ())
        )
        if not targets:
            targets = ("broad_equities",)
        mechanism = (
            "Direction is unresolved; the headline indicates exposure through "
            + ", ".join(channels or ("unclassified",))
            + ", but additional causal evidence is required."
        )
        return tuple(
            (
                target,
                TransmissionDirection.NEUTRAL,
                0.10,
                mechanism,
                "unresolved",
                ("unresolved-channel-fallback",),
            )
            for target in targets
        )

    def _aggregate_transmissions(
        self,
        drivers: tuple[EventDriver, ...],
    ) -> tuple[tuple[str, TransmissionDirection, float, str, str, tuple[str, ...]], ...]:
        grouped: dict[str, list[tuple[EventDriver, RuleTransmission]]] = {}
        for driver in drivers:
            for transmission in driver.transmissions:
                grouped.setdefault(transmission.target_identifier, []).append(
                    (driver, transmission)
                )
        result = []
        for target, values in sorted(grouped.items()):
            positive = sum(
                transmission.magnitude * driver.confidence
                for driver, transmission in values
                if transmission.direction is TransmissionDirection.POSITIVE
            )
            negative = sum(
                transmission.magnitude * driver.confidence
                for driver, transmission in values
                if transmission.direction is TransmissionDirection.NEGATIVE
            )
            mixed = sum(
                transmission.magnitude * driver.confidence
                for driver, transmission in values
                if transmission.direction is TransmissionDirection.MIXED
            )
            total = positive + negative + mixed
            if total <= 0.0:
                direction = TransmissionDirection.NEUTRAL
                magnitude = 0.0
            elif mixed > 0.0 or (
                positive > 0.0
                and negative > 0.0
                and min(positive, negative) / max(positive, negative)
                >= self.policy.mixed_direction_conflict_ratio
            ):
                direction = TransmissionDirection.MIXED
                magnitude = min(1.0, max(positive, negative, mixed) / max(len(values), 1))
            elif positive > negative:
                direction = TransmissionDirection.POSITIVE
                magnitude = min(1.0, (positive - negative) / max(len(values), 1))
            elif negative > positive:
                direction = TransmissionDirection.NEGATIVE
                magnitude = min(1.0, (negative - positive) / max(len(values), 1))
            else:
                direction = TransmissionDirection.NEUTRAL
                magnitude = 0.0
            mechanisms = _unique(transmission.mechanism for _, transmission in values)
            horizons = _unique(transmission.horizon for _, transmission in values)
            driver_ids = _unique(driver.rule_identifier for driver, _ in values)
            result.append(
                (
                    target,
                    direction,
                    round(magnitude, 8),
                    " | ".join(mechanisms),
                    ",".join(horizons),
                    driver_ids,
                )
            )
        return tuple(result)

    def _confirm(
        self,
        predicted: tuple[
            tuple[str, TransmissionDirection, float, str, str, tuple[str, ...]], ...
        ],
        observations: tuple[MarketObservation, ...],
        *,
        base_evidence: tuple[str, ...],
    ) -> tuple[
        tuple[MarketTransmission, ...],
        float,
        float,
        tuple[str, ...],
    ]:
        by_target: dict[str, list[MarketObservation]] = {}
        for item in observations:
            by_target.setdefault(item.exposure_identifier, []).append(item)
        transmissions = []
        confirmations: list[tuple[float, float]] = []
        observable_weight = sum(
            magnitude
            for _, direction, magnitude, _, _, _ in predicted
            if direction in {TransmissionDirection.POSITIVE, TransmissionDirection.NEGATIVE}
            and magnitude > 0.0
        )
        observed_weight = 0.0
        contradictions = []
        for target, direction, magnitude, mechanism, horizon, driver_ids in predicted:
            relevant = by_target.get(target, [])
            target_values = []
            for observation in relevant:
                move_strength = min(
                    abs(observation.return_change) / self.policy.full_confirmation_move,
                    1.0,
                )
                if abs(observation.return_change) < self.policy.minimum_observed_move:
                    move_strength = 0.0
                if direction.sign == 0.0:
                    continue
                if observation.return_change * direction.sign > 0.0:
                    target_values.append(move_strength)
                elif observation.return_change * direction.sign < 0.0:
                    target_values.append(0.0)
                    contradictions.append(
                        f"{target} moved {observation.return_change:+.4f}, opposite the expected {direction.value} direction."
                    )
            target_confirmation = (
                sum(target_values) / len(target_values) if target_values else 0.0
            )
            if relevant and direction.sign != 0.0:
                observed_weight += magnitude
                confirmations.append((target_confirmation, magnitude))
            causal_confidence = min(
                1.0,
                0.45 + 0.45 * magnitude,
            )
            final_confidence = round(
                min(1.0, 0.70 * causal_confidence + 0.30 * target_confirmation),
                8,
            )
            evidence = _unique(
                (
                    *base_evidence,
                    *(item.identifier for item in relevant),
                    *(
                        evidence_identifier
                        for item in relevant
                        for evidence_identifier in item.evidence_identifiers
                    ),
                )
            )
            transmissions.append(
                MarketTransmission(
                    target_identifier=target,
                    direction=direction,
                    magnitude=magnitude,
                    confidence=final_confidence,
                    mechanism=mechanism,
                    horizon=horizon,
                    evidence_identifiers=evidence,
                    contributing_driver_identifiers=driver_ids,
                )
            )
        total_confirmation_weight = sum(weight for _, weight in confirmations)
        confirmation = (
            sum(value * weight for value, weight in confirmations)
            / total_confirmation_weight
            if total_confirmation_weight
            else 0.0
        )
        coverage = (
            min(1.0, observed_weight / observable_weight)
            if observable_weight > 0.0
            else 0.0
        )
        return (
            tuple(transmissions),
            round(confirmation, 8),
            round(coverage, 8),
            _unique(contradictions),
        )


class GovernedEventMarketService:
    """Compose causal transmission evidence with existing portfolio-review policy."""

    def __init__(
        self,
        *,
        engine: EventToMarketEngine | None = None,
        portfolio_analyzer: CurrentEventPortfolioAnalyzer | None = None,
    ) -> None:
        self.engine = engine or EventToMarketEngine()
        self.portfolio_analyzer = portfolio_analyzer or CurrentEventPortfolioAnalyzer()

    def assess(
        self,
        record: DecisionInformationRecord,
        *,
        event_cluster: object,
        observations: tuple[MarketObservation, ...],
        portfolio_identifier: str,
        owned_instrument_identifiers: tuple[str, ...],
        portfolio_exposure_map: Mapping[str, Sequence[str]],
        candidate_exposure_map: Mapping[str, Sequence[str]],
        assessed_at: datetime,
    ) -> GovernedEventMarketResult:
        assessment = self.engine.assess(
            record,
            event_cluster=event_cluster,
            observations=observations,
            assessed_at=assessed_at,
            owned_instrument_identifiers=owned_instrument_identifiers,
            exposure_map=portfolio_exposure_map,
        )
        portfolio_impact = self.portfolio_analyzer.assess(
            record,
            portfolio_identifier=portfolio_identifier,
            assessed_at=assessed_at,
            owned_instrument_identifiers=owned_instrument_identifiers,
            market_confirmation=assessment.market_confirmation,
        )
        candidate_evidence = self.engine.candidate_evidence(
            assessment,
            candidate_exposure_map=candidate_exposure_map,
        )
        return GovernedEventMarketResult(
            assessment=assessment,
            portfolio_impact=portfolio_impact,
            candidate_evidence=candidate_evidence,
            requires_cio_review=(
                assessment.eligible_for_cio_context
                and portfolio_impact.requires_cio_review
            ),
        )


class SQLiteEventMarketStore:
    """Idempotent append-only persistence for event-market assessments."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_market_assessments (
                    identifier TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS event_market_no_update
                BEFORE UPDATE ON event_market_assessments
                BEGIN SELECT RAISE(
                    ABORT,
                    'event-market assessments are append-only'
                ); END;
                CREATE TRIGGER IF NOT EXISTS event_market_no_delete
                BEFORE DELETE ON event_market_assessments
                BEGIN SELECT RAISE(
                    ABORT,
                    'event-market assessments are append-only'
                ); END;
                """
            )

    def append(
        self,
        assessment: EventMarketAssessment,
        *,
        recorded_at: datetime,
    ) -> None:
        if not isinstance(assessment, EventMarketAssessment):
            raise TypeError("assessment must be EventMarketAssessment")
        timestamp = _aware(recorded_at, field_name="recorded_at")
        payload = json.dumps(
            assessment.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                """
                SELECT payload_hash
                FROM event_market_assessments
                WHERE identifier = ?
                """,
                (assessment.identifier,),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise ValueError(
                        "event-market identifier already exists with different content"
                    )
                return
            connection.execute(
                """
                INSERT INTO event_market_assessments
                (identifier, recorded_at, payload_json, payload_hash)
                VALUES (?, ?, ?, ?)
                """,
                (
                    assessment.identifier,
                    timestamp.isoformat(),
                    payload,
                    digest,
                ),
            )

