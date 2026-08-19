"""Authoritative production bridge from qualified evidence to paper eligibility.

The production publisher already owns discovery, point-in-time investment evidence,
full-universe screening, and exact active-universe persistence.  This module consumes
those completed artifacts and proves which *exact structural instruments* also have a
complete operational paper-ownership stack.

Provider visibility never grants authority.  Complete graphs are reconciled through
the append-only ``InstrumentPaperEligibility`` authority; degradation or removal from
the active publication appends a suspension.  The bridge grants neither CIO authority
nor real-money authority.
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
    InstrumentPaperEligibilityCertification,
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
    # Candidate identifiers refer to immutable screening payloads.  A capability
    # suffix states exactly which qualified fact/model contract is being relied on.
    return f"qualified-candidate:{candidate.identifier}:capability:{capability}"


def _profile(instrument: object, *, universe_identifier: str):
    builder = getattr(instrument, "profile", None)
    if not callable(builder):
        return None
    try:
        return builder(universe_identifier=universe_identifier)
    except (KeyError, TypeError, ValueError):
        return None


def _structural_asset_class(instrument: object, candidate: CandidateDecisionRecord):
    return getattr(
        instrument,
        "execution_asset_class",
        candidate.instrument.asset_class,
    )


def _base_capabilities(
    *,
    candidate: CandidateDecisionRecord,
    profile: object | None,
) -> set[str]:
    values: set[str] = set()
    instrument = candidate.instrument
    if (
        instrument.instrument_id
        and instrument.symbol
        and instrument.venue
        and instrument.country_code
        and instrument.security_master_snapshot_identifier
        and instrument.security_master_record_identifiers
    ):
        values.add("identity")
    if candidate.current_price > 0.0 and candidate.evidence_identifiers:
        values.add("market_data")
    quality = candidate.evidence_quality
    if quality.score >= 0.70 and quality.ceiling >= 0.50 and candidate.evidence_identifiers:
        values.add("evidence")
    if candidate.scenario_distribution and candidate.model_versions:
        values.update(("valuation", "model_compatibility"))
    if candidate.transaction_cost_bps >= 0.0 and candidate.slippage_bps >= 0.0:
        values.add("transaction_costs")
    if (
        instrument.average_daily_dollar_volume
        >= MINIMUM_AVERAGE_DAILY_DOLLAR_VOLUME
        and candidate.liquidity_score >= 0.70
    ):
        values.add("liquidity")
    if candidate.maximum_position_weight > 0.0:
        values.add("risk_controls")

    if profile is None:
        return values
    if getattr(profile, "trading_session_model", None) is not None:
        values.add("trading_calendar")
    if _text(getattr(profile, "execution_model_version", None)):
        values.update(("execution_model", "execution_simulation"))
    if _text(getattr(profile, "custody_settlement_identifier", None)):
        values.add("custody_settlement")
    approval = getattr(getattr(profile, "approval_state", None), "value", None)
    if approval == "paper_eligible" and _text(getattr(profile, "approval_identifier", None)):
        values.add("portfolio_construction")
    if (
        _text(getattr(profile, "settlement_currency", None))
        and _positive(getattr(profile, "contract_multiplier", 0.0)) > 0.0
    ):
        # These proofs are anchored to the canonical multi-asset paper ledger, whose
        # accounting and reconciliation remain independently verified after every fill.
        values.update(
            ("accounting_treatment", "accounting_simulation", "reconciliation")
        )
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
    custody = _text(getattr(profile, "custody_settlement_identifier", None))
    session = getattr(profile, "trading_session_model", None)
    execution = _text(getattr(profile, "execution_model_version", None))
    lifecycle = _text(getattr(profile, "lifecycle_model_version", None))

    if family in {AssetFamily.EQUITY, AssetFamily.FUND}:
        if candidate.instrument.security_master_record_identifiers and custody:
            values.update(("corporate_actions", "settlement_cycle"))
        if session is not None:
            values.add("exchange_session")
        return values

    if family is AssetFamily.FIXED_INCOME:
        # Direct debt remains deliberately fail-closed until actual terms exist.
        # Bond funds are structurally FUND instruments and do not enter this branch.
        if getattr(instrument, "expiration_at", None) is not None:
            values.add("maturity_terms")
        coupon = getattr(instrument, "coupon_rate", None)
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
            values.update(("initial_margin", "maintenance_margin"))
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
        if lifecycle or execution:
            values.add("exercise_assignment")
        if candidate.payoff_distribution and _text(getattr(profile, "contract_model_version", None)):
            values.add("greeks_model")
        if _text(getattr(profile, "margin_model_version", None)):
            values.add("option_margin")
        return values

    if family is AssetFamily.FX:
        provider_symbol = _text(getattr(instrument, "provider_symbol", None))
        if provider_symbol or "/" in candidate.instrument.symbol:
            values.add("currency_pair")
        # The direct FX execution model owns overnight financing/rollover simulation;
        # a separate lifecycle string is optional metadata, not a second authority.
        if execution:
            values.update(("financing_model", "rollover_model"))
        if custody:
            values.add("fx_settlement")
        return values

    if family is AssetFamily.CRYPTO:
        model_value = _text(getattr(session, "value", session)).lower()
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


def _candidate_evidence(
    candidate: CandidateDecisionRecord,
    instrument: object,
    *,
    universe_identifier: str,
    evaluated_at: datetime,
) -> InstrumentCapabilityEvidence:
    asset_class = _structural_asset_class(instrument, candidate)
    instrument_type = _text(
        getattr(instrument, "instrument_type", candidate.instrument.instrument_type)
    )
    family = family_for_instrument(asset_class, instrument_type)
    profile = _profile(instrument, universe_identifier=universe_identifier)
    capabilities = _base_capabilities(candidate=candidate, profile=profile)
    capabilities.update(
        _family_capabilities(
            family=family,
            candidate=candidate,
            instrument=instrument,
            profile=profile,
        )
    )
    review_at = candidate.review_at.astimezone(timezone.utc)
    expires_at = min(
        evaluated_at + CAPABILITY_EVIDENCE_LIFETIME,
        review_at if review_at > evaluated_at else evaluated_at + timedelta(hours=1),
    )
    sources = tuple(
        dict.fromkeys(
            value
            for value in (
                candidate.identifier,
                candidate.instrument.security_master_snapshot_identifier,
                *candidate.instrument.security_master_record_identifiers,
                *candidate.evidence_identifiers,
            )
            if _text(value)
        )
    )
    return InstrumentCapabilityEvidence(
        instrument_identifier=candidate.instrument.instrument_id,
        symbol=candidate.instrument.symbol,
        asset_class=asset_class,
        venue=candidate.instrument.venue,
        country_code=candidate.instrument.country_code,
        instrument_type=instrument_type,
        observed_at=evaluated_at,
        expires_at=expires_at,
        capabilities=frozenset(capabilities),
        proof_identifiers={name: _proof(candidate, name) for name in capabilities},
        source_identifiers=sources or (candidate.identifier,),
        average_daily_dollar_volume=candidate.instrument.average_daily_dollar_volume,
        minimum_average_daily_dollar_volume=MINIMUM_AVERAGE_DAILY_DOLLAR_VOLUME,
        leverage_multiplier=abs(candidate.instrument.leverage_multiplier),
        maximum_gross_leverage=max(1.0, abs(candidate.instrument.leverage_multiplier)),
    )


def _incomplete_evidence(
    instrument: object,
    *,
    evaluated_at: datetime,
    source_identifier: str,
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
            {"identity": f"{source_identifier}:identity:{identifier}"}
            if identity_complete
            else {}
        ),
        source_identifiers=(source_identifier,),
        average_daily_dollar_volume=0.0,
        minimum_average_daily_dollar_volume=MINIMUM_AVERAGE_DAILY_DOLLAR_VOLUME,
        leverage_multiplier=1.0,
        maximum_gross_leverage=1.0,
    )


def _omission_evidence(
    certification: InstrumentPaperEligibilityCertification,
    *,
    evaluated_at: datetime,
    publication_identifier: str,
) -> InstrumentCapabilityEvidence:
    return InstrumentCapabilityEvidence(
        instrument_identifier=certification.instrument_identifier,
        symbol=certification.symbol,
        asset_class=certification.asset_class,
        venue=certification.venue,
        country_code=certification.country_code,
        instrument_type=certification.instrument_type,
        observed_at=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=1),
        capabilities=frozenset(),
        proof_identifiers={},
        source_identifiers=(f"active-universe-omission:{publication_identifier}",),
        average_daily_dollar_volume=0.0,
        minimum_average_daily_dollar_volume=(
            certification.minimum_average_daily_dollar_volume
        ),
        leverage_multiplier=1.0,
        maximum_gross_leverage=certification.maximum_gross_leverage,
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


def _policy_from_certification(
    certification: InstrumentPaperEligibilityCertification,
    *,
    code_version: str,
) -> EligibilityCertificationPolicy:
    return EligibilityCertificationPolicy(
        asset_class_approval_identifier=certification.asset_class_approval_identifier,
        governance_identifier=GOVERNANCE_IDENTIFIER,
        process_version=PROCESS_VERSION,
        code_version=code_version,
        maximum_position_weight=certification.maximum_position_weight,
        maximum_participation_rate=certification.maximum_participation_rate,
        certification_lifetime=CERTIFICATION_LIFETIME,
    )


def reconcile_production_capability_authority(
    *,
    settings: object,
    publication_identifier: str,
    screening_cycle_identifier: str,
    evaluated_at: datetime,
) -> ProductionCapabilityAuthorityResult:
    """Reconcile the exact active publication into append-only paper authority."""

    timestamp = _aware(evaluated_at, field_name="evaluated_at")
    eligible_identifier = str(publication_identifier).strip()
    root = Path(getattr(settings, "portfolio_database")).expanduser().parent
    active_path = root / "active-paper-universe.json"
    persisted_identifier, universe = load_current_active_paper_universe(
        active_path=active_path
    )
    if persisted_identifier != eligible_identifier:
        raise ValueError(
            "production capability authority requires the exact active-universe publication"
        )

    screening_store = SQLiteFullUniverseScreeningStore(
        getattr(settings, "full_universe_screening_database")
    )
    publication = screening_store.publication(screening_cycle_identifier)
    if publication is None:
        raise ValueError("production capability authority requires completed screening")
    if publication.cycle_identifier != screening_cycle_identifier:
        raise ValueError("screening publication belongs to another cycle")
    if publication.universe_snapshot_identifier != eligible_identifier:
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
    current_identifiers: set[str] = set()
    for instrument in universe.instruments:
        identifier = _text(getattr(instrument, "instrument_identifier", None))
        current_identifiers.add(identifier)
        candidate = candidate_by_instrument.get(identifier)
        evidence = (
            _incomplete_evidence(
                instrument,
                evaluated_at=timestamp,
                source_identifier=f"screening-exclusion:{screening_cycle_identifier}",
            )
            if candidate is None
            else _candidate_evidence(
                candidate,
                instrument,
                universe_identifier=universe.identifier,
                evaluated_at=timestamp,
            )
        )
        evaluations.append(evaluate_capabilities(evidence, evaluated_at=timestamp))
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

    # A still-active certification from an older publication must not survive removal
    # from the exact current universe.  Append a suspension rather than deleting or
    # mutating history.
    for identifier in sorted(store.active_identifiers(evaluated_at=timestamp) - current_identifiers):
        active = store.active(identifier, evaluated_at=timestamp)
        if active is None:
            continue
        transitions.append(
            factory.reconcile(
                _omission_evidence(
                    active,
                    evaluated_at=timestamp,
                    publication_identifier=eligible_identifier,
                ),
                policy=_policy_from_certification(active, code_version=code_version),
                evaluated_at=timestamp,
            )
        )

    store.verify_integrity()
    active_identifiers = tuple(
        item.instrument_identifier
        for item in evaluations
        if store.active(item.instrument_identifier, evaluated_at=timestamp) is not None
    )
    cio_eligible = tuple(
        item.instrument.instrument_id
        for item in candidates
        if item.instrument.instrument_id in active_identifiers
    )
    coverage = investability_coverage(
        tuple(evaluations),
        paper_certified_identifiers=active_identifiers,
        cio_eligible_identifiers=cio_eligible,
    )
    actions = [item.action for item in transitions]
    return ProductionCapabilityAuthorityResult(
        evaluated_at=timestamp,
        publication_identifier=eligible_identifier,
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
