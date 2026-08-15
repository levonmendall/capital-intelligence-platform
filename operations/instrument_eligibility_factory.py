"""Automatic bridge from the universal capability graph to paper eligibility.

This module is deliberately the only automatic promotion path. It consumes
already-qualified, point-in-time capability proofs and writes immutable events to
the existing instrument paper-eligibility authority. It never consumes raw
provider discovery as authority and never grants CIO or real-money authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from governance.instrument_paper_eligibility import (
    InstrumentPaperEligibilityCertification,
    InstrumentPaperEligibilityState,
    SQLiteInstrumentPaperEligibilityStore,
)
from operations.universal_capability_graph import (
    InstrumentCapabilityEvidence,
    evaluate_capabilities,
)


def _aware(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: object, *, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _identifier(*parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"instrument-paper-capability:{digest}"


@dataclass(frozen=True, slots=True)
class EligibilityCertificationPolicy:
    """Governed limits and lineage supplied by the portfolio policy plane."""

    asset_class_approval_identifier: str
    governance_identifier: str
    process_version: str
    code_version: str
    maximum_position_weight: float
    maximum_participation_rate: float
    certification_lifetime: timedelta = timedelta(days=1)

    def __post_init__(self) -> None:
        for name in (
            "asset_class_approval_identifier",
            "governance_identifier",
            "process_version",
            "code_version",
        ):
            _text(getattr(self, name), name=name)
        for name in ("maximum_position_weight", "maximum_participation_rate"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not 0.0 < float(value) <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]")
        if not isinstance(self.certification_lifetime, timedelta):
            raise TypeError("certification_lifetime must be timedelta")
        if self.certification_lifetime <= timedelta(0):
            raise ValueError("certification_lifetime must be positive")


@dataclass(frozen=True, slots=True)
class EligibilityTransition:
    instrument_identifier: str
    action: str
    certification_identifier: str | None
    blockers: tuple[str, ...]
    provider_authority: bool = False
    cio_authority: bool = False
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_identifier": self.instrument_identifier,
            "action": self.action,
            "certification_identifier": self.certification_identifier,
            "blockers": list(self.blockers),
            "provider_authority": False,
            "cio_authority": False,
            "real_money_authorized": False,
        }


class AutomaticInstrumentEligibilityFactory:
    """Append certification/suspension events from deterministic capability proof."""

    GRAPH_VERSION = "universal-capability-graph.v1"

    def __init__(self, store: SQLiteInstrumentPaperEligibilityStore) -> None:
        if not isinstance(store, SQLiteInstrumentPaperEligibilityStore):
            raise TypeError("store must be SQLiteInstrumentPaperEligibilityStore")
        self.store = store

    @staticmethod
    def _proof(evidence: InstrumentCapabilityEvidence, capability: str) -> str:
        value = evidence.proof_identifiers.get(capability, "")
        return _text(value, name=f"proof:{capability}")

    def _certification(
        self,
        evidence: InstrumentCapabilityEvidence,
        *,
        policy: EligibilityCertificationPolicy,
        evaluated_at: datetime,
    ) -> InstrumentPaperEligibilityCertification:
        timestamp = _aware(evaluated_at, name="evaluated_at")
        evaluation = evaluate_capabilities(evidence, evaluated_at=timestamp)
        if not evaluation.certifiable:
            raise ValueError(
                "instrument capability graph is incomplete: "
                + ", ".join(evaluation.blockers or evaluation.missing_capabilities)
            )
        expires_at = min(evidence.expires_at, timestamp + policy.certification_lifetime)
        if expires_at <= timestamp:
            raise ValueError("capability evidence cannot support a future certification")
        proof_sources = tuple(
            dict.fromkeys(
                (
                    *evidence.source_identifiers,
                    *(
                        f"capability-proof:{name}:{identifier}"
                        for name, identifier in sorted(evidence.proof_identifiers.items())
                    ),
                    f"capability-graph:{self.GRAPH_VERSION}",
                )
            )
        )
        identifier = _identifier(
            evidence.instrument_identifier,
            evidence.observed_at.isoformat(),
            expires_at.isoformat(),
            policy.asset_class_approval_identifier,
            policy.governance_identifier,
            policy.process_version,
            policy.code_version,
            self.GRAPH_VERSION,
        )
        return InstrumentPaperEligibilityCertification(
            identifier=identifier,
            instrument_identifier=evidence.instrument_identifier,
            symbol=evidence.symbol,
            asset_class=evidence.asset_class,
            venue=evidence.venue,
            country_code=evidence.country_code,
            instrument_type=evidence.instrument_type,
            state=InstrumentPaperEligibilityState.CERTIFIED,
            approved_at=timestamp,
            effective_at=timestamp,
            expires_at=expires_at,
            minimum_average_daily_dollar_volume=evidence.minimum_average_daily_dollar_volume,
            maximum_position_weight=policy.maximum_position_weight,
            maximum_participation_rate=policy.maximum_participation_rate,
            maximum_gross_leverage=evidence.maximum_gross_leverage,
            market_data_certification_identifier=self._proof(evidence, "market_data"),
            identity_certification_identifier=self._proof(evidence, "identity"),
            evidence_certification_identifier=self._proof(evidence, "evidence"),
            valuation_model_version=self._proof(evidence, "valuation"),
            trading_calendar_certification_identifier=self._proof(evidence, "trading_calendar"),
            transaction_cost_model_version=self._proof(evidence, "transaction_costs"),
            liquidity_model_version=self._proof(evidence, "liquidity"),
            accounting_model_version=self._proof(evidence, "accounting_treatment"),
            execution_model_version=self._proof(evidence, "execution_model"),
            risk_model_version=self._proof(evidence, "risk_controls"),
            portfolio_construction_model_version=self._proof(evidence, "portfolio_construction"),
            custody_settlement_identifier=self._proof(evidence, "custody_settlement"),
            asset_class_approval_identifier=policy.asset_class_approval_identifier,
            governance_identifier=f"{policy.governance_identifier}|{self.GRAPH_VERSION}",
            process_version=policy.process_version,
            code_version=policy.code_version,
            source_identifiers=proof_sources,
            limitations=(
                "paper-only capability certification; CIO authority remains separate",
                "automatic suspension applies when required capability proof degrades",
            ),
        )

    def reconcile(
        self,
        evidence: InstrumentCapabilityEvidence,
        *,
        policy: EligibilityCertificationPolicy,
        evaluated_at: datetime,
    ) -> EligibilityTransition:
        """Certify a complete graph or suspend an active certification on degradation."""

        timestamp = _aware(evaluated_at, name="evaluated_at")
        evaluation = evaluate_capabilities(evidence, evaluated_at=timestamp)
        active = self.store.active(evidence.instrument_identifier, evaluated_at=timestamp)
        if evaluation.certifiable:
            certification = self._certification(
                evidence, policy=policy, evaluated_at=timestamp
            )
            # Avoid append churn while the exact active authority is backed by the
            # same point-in-time capability proof and policy lineage.
            if active is not None and (
                active.identifier == certification.identifier
                or (
                    active.evidence_certification_identifier
                    == certification.evidence_certification_identifier
                    and active.identity_certification_identifier
                    == certification.identity_certification_identifier
                    and active.governance_identifier == certification.governance_identifier
                    and active.expires_at >= certification.expires_at
                )
            ):
                return EligibilityTransition(
                    instrument_identifier=evidence.instrument_identifier,
                    action="unchanged_certified",
                    certification_identifier=active.identifier,
                    blockers=(),
                )
            self.store.append(certification)
            return EligibilityTransition(
                instrument_identifier=evidence.instrument_identifier,
                action="certified",
                certification_identifier=certification.identifier,
                blockers=(),
            )

        if active is None:
            return EligibilityTransition(
                instrument_identifier=evidence.instrument_identifier,
                action="research_only",
                certification_identifier=None,
                blockers=evaluation.blockers,
            )

        suspension = replace(
            active,
            identifier=_identifier(
                active.identifier,
                "suspended",
                timestamp.isoformat(),
                *evaluation.blockers,
            ),
            state=InstrumentPaperEligibilityState.SUSPENDED,
            approved_at=timestamp,
            effective_at=timestamp,
            # Cover the remainder of the superseded authority so an expired
            # suspension cannot accidentally reactivate the earlier certification.
            expires_at=active.expires_at,
            governance_identifier=f"{policy.governance_identifier}|{self.GRAPH_VERSION}|automatic-suspension",
            process_version=policy.process_version,
            code_version=policy.code_version,
            limitations=tuple(
                dict.fromkeys(
                    (*active.limitations, *(f"capability blocker: {x}" for x in evaluation.blockers))
                )
            ),
        )
        self.store.append(suspension)
        return EligibilityTransition(
            instrument_identifier=evidence.instrument_identifier,
            action="suspended",
            certification_identifier=suspension.identifier,
            blockers=evaluation.blockers,
        )


__all__ = [
    "AutomaticInstrumentEligibilityFactory",
    "EligibilityCertificationPolicy",
    "EligibilityTransition",
]
