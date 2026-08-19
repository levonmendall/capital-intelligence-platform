"""Authoritative production bridge from qualified evidence to paper eligibility.

The production publication already owns discovery, point-in-time evidence, screening,
and exact active-universe persistence.  This module consumes those completed artifacts
and proves which exact instruments have a complete operational stack.  It never uses
provider visibility as authority and it never grants CIO or real-money authority.

A complete graph is reconciled through the existing append-only
``InstrumentPaperEligibility`` authority.  If a previously certified instrument loses
required proof, the same factory appends a suspension.  Bootstrap instruments retain
their independent legacy certification, but they are still measured here so global
investability coverage is truthful.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from cio.models import CandidateDecisionRecord
from governance.instrument_paper_eligibility import (
    SQLiteInstrumentPaperEligibilityStore,
)
from operations.free_paper_pilot import load_current_active_paper_universe
from operations.instrument_eligibility_factory import (
    AutomaticInstrumentEligibilityFactory,
    EligibilityCertificationPolicy,
    EligibilityTransition,
)
from operations.universal_capability_graph import (
    AssetFamily,
    InstrumentCapabilityEvidence,
    evaluate_capabilities,
    family_for_instrument,
    investability_coverage,
)
from screening import SQLiteFullUniverseScreeningStore, candidate_from_payload


MINIMUM_AVERAGE_DAILY_DOLLAR_VOLUME = 1_000_000.0
CAPABILITY_EVIDENCE_LIFETIME = timedelta(hours=24)
CERTIFICATION_LIFETIME = timedelta(hours=24)
PROCESS_VERSION = "production-capability-authority.v1"
GOVERNANCE_IDENTIFIER = "governance:compounding-paper-capability:v1"


@dataclass(frozen=True, slots=True)
class ProductionCapabilityAuthorityResult:
    evaluated_at: datetime
    publication_identifier: str
    screening_cycle_identifier: str
    instrument_count: int
    candidate_count: int
    certifiable_count: int
    certified_count: int
    suspended_count: int
    research_only_count: int
    transitions: tuple[EligibilityTransition, ...]
    coverage: Mapping[str, Any]
    database_path: str
    paper_only: bool = True
    real_money_authorized: bool = False
    schema_version: str = "production-capability-authority-result.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evaluated_at": self.evaluated_at.isoformat(),
            "publication_identifier": self.publication_identifier,
            "screening_cycle_identifier": self.screening_cycle_identifier,
            "instrument_count": self.instrument_count,
            "candidate_count": self.candidate_count,
            "certifiable_count": self.certifiable_count,
            "certified_count": self.certified_count,
            "suspended_count": self.suspended_count,
            "research_only_count": self.research_only_count,
            "transitions": [item.to_dict() for item in self.transitions],
            "coverage": dict(self.coverage),
            "database_path": self.database_path,
            "paper_only": True,
            "real_money_authorized": False,
        }


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: object) -> str:
    return str(value or "").strip()


def _positive(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default)
    resolved = float(value)
    return resolved if isfinite(resolved) and resolved > 0.0 else float(default)


def _proof(candidate: CandidateDecisionRecord, capability: str) -> str:
    # The candidate identifier refers to the immutable screening payload persisted by
    # the governed publication.  Capability-specific suffixes make the proof contract
    # explicit without pretending a raw provider response is itself authority.
    return f"qualified-candidate:{candidate.identifier}:capability:{capability}"


def _profile(instrument: object, *, universe_identifier: str):
    builder = getattr(instrument, "profile", None)
    if not callable(builder):
        return None
    try:
        return builder(universe_identifier=universe_identifier)
    except (KeyError, TypeError, ValueError):
        return None


def _base_capabilities(
    *,
    candidate: CandidateDecisionRecord,
    instrument: object,
    profile: object | None,
) -> set[str]:
    values: set[str] = set()
    if (
        candidate.instrument.instrument_id
        and candidate.instrument.symbol
        and candidate.instrument.venue
        and candidate.instrument.country_code
        and candidate.instrument.security_master_snapshot_identifier
        and candidate.instrument.security_master_record_identifiers
    ):
        values.add("identity")
    if candidate.current_price > 0.0 and candidate.evidence_identifiers:
        values.add("market_data")
    quality = candidate.evidence_quality
    if (
        quality.score >= 0.70
        and quality.ceiling >= 0.50
        and candidate.evidence_identifiers
    ):
        values.add("evidence")
    if (
        candidate.estimated_fair_value >= 0.0
        and candidate.scenario_distribution
        and candidate.model_versions
    ):
        values.add("valuation")
        values.add("model_compatibility")
    if candidate.transaction_cost_bps >= 0.0 and candidate.slippage_bps >= 0.0:
        values.add("transaction_costs")
    if (
        candidate.instrument.average_daily_dollar_volume
        >= MINIMUM_AVERAGE_DAILY_DOLLAR_VOLUME
        and candidate.liquidity_score >= 0.70
    ):
        values.add("liquidity")
    if candidate.expected_downside <= 0.0 and candidate.maximum_position_weight > 0.0:
        values.add("risk_controls")

    if profile is not None:
        if getattr(profile, "trading_session_model", None) is not None:
            values.add("trading_calendar")
        if _text(getattr(profile, "execution_model_version", None)):
            values.add("execution_model")
            values.add("execution_simulation")
        if _text(getattr(profile, "custody_settlement_identifier", None)):
            values.add("custody_settlement")
        approval = getattr(getattr(profile, "approval_state", None), "value", None)
        if approval == "paper_eligible" and _text(
            getattr(profile, "approval_identifier", None)
        ):
            values.add("portfolio_construction")
        if (
            _text(getattr(profile, "settlement_currency", None))
            and _positive(getattr(profile, "contract_multiplier", 0.0)) > 0.0
        ):
            values.add("accounting_treatment")
            values.add("accounting_simulation")
            values.add("reconciliation")
    return values


def _family_capabilities(
    *,
    family: AssetFamily | None,
    candidate: CandidateDecisionRecord,
    instrument: object,
    profile: object | None,
) -> set[str]:
    if family is None or profile is None:
        return set()
    values: set[str] = set()
    lifecycle = _text(getattr(profile, "lifecycle_model_version", None))
    custody = _text(getattr(profile, "custody_settlement_identifier", None))
    session = getattr(profile, "trading_session_model", None)

    if family in {AssetFamily.EQUITY, AssetFamily.FUND}:
        # Listed-paper lifecycle is anchored to the certified security-master record,
        # the session model, and the custody/settlement contract.  Corporate actions
        # are treated as a lifecycle/reconciliation capability, not as a price-feed
        # side effect.
        if candidate.instrument.security_master_record_identifiers and custody:
            values.add("corporate_actions")
            values.add("settlement_cycle")
        if session is not None:
            values.add("exchange_session")
        return values

    if family is AssetFamily.FIXED_INCOME:
        # Direct debt stays fail-closed until actual terms exist.  Listed bond funds
        # resolve structurally as FUND and do not enter this branch.
        maturity = getattr(instrument, "expiration_at", None)
        coupon = getattr(instrument, "coupon_rate", None)
        if maturity is not None:
            values.add("maturity_terms")
        if isinstance(coupon, (int, float)) and not isinstance(coupon, bool):
            values.add("coupon_accrual")
        if lifecycle:
            values.add("duration_model")
        if custody:
            values.add("bond_settlement")
        return values

    if family is AssetFamily.FUTURE:
        if getattr(instrument, "expiration_at", None) is not None:
            values.add("contract_expiry")
        if _text(getattr(profile, "roll_model_version", None)):
            values.add("roll_model")
        if _positive(getattr(profile, "contract_multiplier", 0.0)) > 0.0:
            values.add("contract_multiplier")
        if _text(getattr(profile, "margin_model_version", None)):
            values.add("initial_margin")
            values.add("maintenance_margin")
        return values

    if family is AssetFamily.OPTION:
        if _positive(getattr(instrument, "strike_price", 0.0)) > 0.0:
            values.add("strike_terms")
        if getattr(instrument, "expiration_at", None) is not None:
            values.add("option_expiry")
        if _text(getattr(instrument, "option_right", None)).lower() in {"call", "put"}:
            values.add("option_side")
        if _positive(getattr(profile, "contract_multiplier", 0.0)) > 0.0:
            values.add("contract_multiplier")
        if lifecycle:
            values.add("exercise_assignment")
        if candidate.payoff_distribution and any(
            "option" in value.lower() or "greek" in value.lower()
            for value in candidate.model_versions
        ):
            values.add("greeks_model")
        if _text(getattr(profile, "margin_model_version", None)):
            values.add("option_margin")
        return values

    if family is AssetFamily.FX:
        provider_symbol = _text(getattr(instrument, "provider_symbol", None))
        if provider_symbol or "/" in candidate.instrument.symbol:
            values.add("currency_pair")
        if lifecycle:
            values.add("financing_model")
            values.add("rollover_model")
        if custody:
            values.add("fx_settlement")
        return values

    if family is AssetFamily.CRYPTO:
        model = getattr(profile, "trading_session_model", None)
        model_value = _text(getattr(model, "value", model)).lower()
        if "24_7" in model_value or "continuous" in model_value:
            values.add("continuous_session")
        if _text(getattr(instrument, "currency", None)) or _text(
            getattr(profile, "settlement_currency", None)
        ):
            values.add("denomination")
        if candidate.instrument.venue:
            values.add("venue_model")
        if custody:
            values.add("custody_simulation")
        return values

    return values


def _evidence_for_candidate(
    candidate: CandidateDecisionRecord,
    instrument: object,
    *,
    universe_identifier: str,
    evaluated_at: datetime,
) -> InstrumentCapabilityEvidence:
    family = family_for_instrument(
        candidate.instrument.asset_class,
        str(getattr(instrument, "instrument_type", candidate.instrument.instrument_type)),
    )
    profile = _profile(instrument, universe_identifier=universe_identifier)
    capabilities = _base_capabilities(
        candidate=candidate,
        instrument=instrument,
        profile=profile,
    )
    capabilities.update(
        _family_capabilities(
            family=family,
            candidate=candidate,
            instrument=instrument,
            profile=profile,
        )
    )
    proof_identifiers = {
        capability: _proof(candidate, capability) for capability in capabilities
    }
    review_at = candidate.review_at.astimezone(timezone.utc)
    expires_at = min(
        evaluated_at + CAPABILITY_EVIDENCE_LIFETIME,
        review_at if review_at > evaluated_at else evaluated_at + timedelta(hours=1),
    )
    return InstrumentCapabilityEvidence(
        instrument_identifier=candidate.instrument.instrument_id,
        symbol=candidate.instrument.symbol,
        asset_class=candidate.instrument.asset_class,
        venue=candidate.instrument.venue,
        country_code=candidate.instrument.country_code,
        instrument_type=str(
            getattr(instrument, "instrument_type", candidate.instrument.instrument_type)
        ),
        observed_at=evaluated_at,
        expires_at=expires_at,
        capabilities=frozenset(capabilities),
        proof_identifiers=proof_identifiers,
        source_identifiers=tuple(
            dict.fromkeys(
                (
                    candidate.identifier,
                    candidate.instrument.security_master_snapshot_identifier,
                    *candidate.instrument.security_master_record_identifiers,
                    *candidate.evidence_identifiers,
                )
            )
        ),
        average_daily_dollar_volume=candidate.instrument.average_daily_dollar_volume,
        minimum_average_daily_dollar_volume=MINIMUM_AVERAGE_DAILY_DOLLAR_VOLUME,
        leverage_multiplier=abs(candidate.instrument.leverage_multiplier),
        maximum_gross_leverage=1.0,
    )


def _incomplete_evidence(
    instrument: object,
    *,
    evaluated_at: datetime,
) -> InstrumentCapabilityEvidence:
    identifier = _text(getattr(instrument, "instrument_identifier", None))
    symbol = _text(getattr(instrument, "symbol", None))
    asset_class = getattr(instrument, "execution_asset_class", None)
    venue = _text(getattr(instrument, "venue", None))
    country = _text(getattr(instrument, "country_code", None))
    instrument_type = _text(getattr(instrument, "instrument_type", None)) or "other"
    identity_complete = bool(identifier and symbol and venue and country)
    capabilities = frozenset({"identity"} if identity_complete else ())
    return InstrumentCapabilityEvidence(
        instrument_identifier=identifier or f"unresolved:{symbol or 'unknown'}",
        symbol=symbol or "UNKNOWN",
        asset_class=asset_class,
        venue=venue or "UNKNOWN",
        country_code=country or "XX",
        instrument_type=instrument_type,
        observed_at=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=1),
        capabilities=capabilities,
        proof_identifiers=(
            {"identity": f"active-universe:{identifier}:identity"}
            if identity_complete
            else {}
        ),
        source_identifiers=(f"active-universe:{identifier or symbol or 'unknown'}",),
        average_daily_dollar_volume=0.0,
        minimum_average_daily_dollar_volume=MINIMUM_AVERAGE_DAILY_DOLLAR_VOLUME,
        leverage_multiplier=abs(
            _positive(getattr(instrument, "leverage_multiplier", 1.0), 1.0)
        ),
        maximum_gross_leverage=1.0,
    )


def _policy(
    *,
    instrument: object,
    candidate: CandidateDecisionRecord | None,
    code_version: str,
) -> EligibilityCertificationPolicy:
    instrument_limit = _positive(getattr(instrument, "maximum_weight", 0.0), 0.01)
    candidate_limit = (
        instrument_limit
        if candidate is None
        else max(0.0001, float(candidate.maximum_position_weight))
    )
    approval = _text(getattr(instrument, "approval_identifier", None)) or (
        f"asset-class-paper-approval:{getattr(instrument, 'execution_asset_class', 'unknown')}"
    )
    return EligibilityCertificationPolicy(
        asset_class_approval_identifier=approval,
        governance_identifier=GOVERNANCE_IDENTIFIER,
        process_version=PROCESS_VERSION,
        code_version=code_version,
        maximum_position_weight=min(instrument_limit, candidate_limit),
        maximum_participation_rate=0.01,
        certification_lifetime=CERTIFICATION_LIFETIME,
    )


def reconcile_production_capability_authority(
    *,
    settings: object,
    publication_identifier: str,
    screening_cycle_identifier: str,
    evaluated_at: datetime,
) -> ProductionCapabilityAuthorityResult:
    """Reconcile exact active-universe instruments into append-only paper authority."""

    timestamp = _aware(evaluated_at, field_name="evaluated_at")
    root = Path(getattr(settings, "portfolio_database")).expanduser().parent
    active_path = root / "active-paper-universe.json"
    persisted_publication, universe = load_current_active_paper_universe(
        active_path=active_path
    )
    if persisted_publication != str(publication_identifier).strip():
        raise ValueError(
            "production capability authority requires the exact active-universe publication"
        )

    screening_store = SQLiteFullUniverseScreeningStore(
        getattr(settings, "full_universe_screening_database")
    )
    publication = screening_store.publication(screening_cycle_identifier)
    if publication is None:
        raise ValueError("production capability authority requires completed screening")
    if publication.identifier != str(publication_identifier).strip().replace(
        "eligible-universe:", "publication:"
    ) and publication.universe_snapshot_identifier != str(publication_identifier).strip():
        # Current publications use separate publication and eligible-universe IDs. The
        # exact eligible-universe identity is the stable linkage that must match.
        if publication.universe_snapshot_identifier != str(publication_identifier).strip():
            raise ValueError("screening publication belongs to another active universe")

    candidates = tuple(candidate_from_payload(item) for item in publication.candidate_payloads)
    candidate_by_instrument = {
        item.instrument.instrument_id: item for item in candidates
    }
    if len(candidate_by_instrument) != len(candidates):
        raise ValueError("screening candidates contain duplicate instrument identities")

    database_path = root / "instrument-paper-eligibility.db"
    os.environ["CAPITAL_INTELLIGENCE_INSTRUMENT_PAPER_ELIGIBILITY_DATABASE"] = str(
        database_path
    )
    store = SQLiteInstrumentPaperEligibilityStore(database_path)
    factory = AutomaticInstrumentEligibilityFactory(store)
    code_version = _text(os.getenv("CAPITAL_INTELLIGENCE_RELEASE")) or "production-runtime"

    transitions: list[EligibilityTransition] = []
    evaluations = []
    for instrument in universe.instruments:
        identifier = _text(getattr(instrument, "instrument_identifier", None))
        candidate = candidate_by_instrument.get(identifier)
        evidence = (
            _incomplete_evidence(instrument, evaluated_at=timestamp)
            if candidate is None
            else _evidence_for_candidate(
                candidate,
                instrument,
                universe_identifier=universe.identifier,
                evaluated_at=timestamp,
            )
        )
        evaluation = evaluate_capabilities(evidence, evaluated_at=timestamp)
        evaluations.append(evaluation)
        transitions.append(
            factory.reconcile(
                evidence,
                policy=_policy(
                    instrument=instrument,
                    candidate=candidate,
                    code_version=code_version,
                ),
                evaluated_at=timestamp,
            )
        )

    store.verify_integrity()
    active_identifiers = tuple(
        item.instrument_identifier
        for item in evaluations
        if store.active(item.instrument_identifier, evaluated_at=timestamp) is not None
    )
    candidate_identifiers = tuple(
        item.instrument.instrument_id
        for item in candidates
        if item.instrument.instrument_id in active_identifiers
    )
    coverage = investability_coverage(
        tuple(evaluations),
        paper_certified_identifiers=active_identifiers,
        cio_eligible_identifiers=candidate_identifiers,
    )
    actions = [item.action for item in transitions]
    return ProductionCapabilityAuthorityResult(
        evaluated_at=timestamp,
        publication_identifier=str(publication_identifier).strip(),
        screening_cycle_identifier=screening_cycle_identifier,
        instrument_count=len(evaluations),
        candidate_count=len(candidates),
        certifiable_count=sum(item.certifiable for item in evaluations),
        certified_count=sum(
            action in {"certified", "unchanged_certified"} for action in actions
        ),
        suspended_count=actions.count("suspended"),
        research_only_count=actions.count("research_only"),
        transitions=tuple(transitions),
        coverage=coverage,
        database_path=str(database_path),
    )


__all__ = [
    "ProductionCapabilityAuthorityResult",
    "reconcile_production_capability_authority",
]
