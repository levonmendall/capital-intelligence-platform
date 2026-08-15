"""Universal, provider-independent instrument capability graph.

The graph answers one question only: is an exact instrument operationally complete
for paper ownership? Discovery, provider visibility, forecasts, and specialist
opinions never grant authority. A complete graph may be handed to the existing
append-only instrument paper-eligibility authority by a separate certification
factory.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

from cio.models import CandidateAssetClass


class AssetFamily(str, Enum):
    EQUITY = "equity"
    FUND = "fund"
    FIXED_INCOME = "fixed_income"
    FUTURE = "future"
    OPTION = "option"
    FX = "fx"
    CRYPTO = "crypto"


UNIVERSAL_CAPABILITIES = frozenset(
    {
        "market_data",
        "identity",
        "evidence",
        "valuation",
        "trading_calendar",
        "transaction_costs",
        "liquidity",
        "accounting_treatment",
        "execution_model",
        "portfolio_construction",
        "custody_settlement",
        "risk_controls",
        "model_compatibility",
        "execution_simulation",
        "accounting_simulation",
        "reconciliation",
    }
)

FAMILY_CAPABILITIES: Mapping[AssetFamily, frozenset[str]] = {
    AssetFamily.EQUITY: frozenset(
        {"corporate_actions", "exchange_session", "settlement_cycle"}
    ),
    AssetFamily.FUND: frozenset(
        {"corporate_actions", "exchange_session", "settlement_cycle"}
    ),
    AssetFamily.FIXED_INCOME: frozenset(
        {"maturity_terms", "coupon_accrual", "duration_model", "bond_settlement"}
    ),
    AssetFamily.FUTURE: frozenset(
        {
            "contract_expiry",
            "roll_model",
            "contract_multiplier",
            "initial_margin",
            "maintenance_margin",
        }
    ),
    AssetFamily.OPTION: frozenset(
        {
            "strike_terms",
            "option_expiry",
            "option_side",
            "contract_multiplier",
            "exercise_assignment",
            "greeks_model",
            "option_margin",
        }
    ),
    AssetFamily.FX: frozenset(
        {"currency_pair", "financing_model", "rollover_model", "fx_settlement"}
    ),
    AssetFamily.CRYPTO: frozenset(
        {"continuous_session", "denomination", "venue_model", "custody_simulation"}
    ),
}

_ASSET_FAMILY_BY_CLASS: Mapping[CandidateAssetClass, AssetFamily] = {
    CandidateAssetClass.US_EQUITY: AssetFamily.EQUITY,
    CandidateAssetClass.INTERNATIONAL_EQUITY: AssetFamily.EQUITY,
    CandidateAssetClass.REAL_ESTATE: AssetFamily.EQUITY,
    CandidateAssetClass.US_ETF: AssetFamily.FUND,
    CandidateAssetClass.CASH_EQUIVALENT: AssetFamily.FUND,
    CandidateAssetClass.ALTERNATIVE: AssetFamily.FUND,
    CandidateAssetClass.VOLATILITY: AssetFamily.FUND,
    CandidateAssetClass.FIXED_INCOME: AssetFamily.FIXED_INCOME,
    CandidateAssetClass.FUTURE: AssetFamily.FUTURE,
    CandidateAssetClass.COMMODITY: AssetFamily.FUTURE,
    CandidateAssetClass.OPTION: AssetFamily.OPTION,
    CandidateAssetClass.FX: AssetFamily.FX,
    CandidateAssetClass.CRYPTO: AssetFamily.CRYPTO,
}


def family_for_asset_class(asset_class: CandidateAssetClass) -> AssetFamily | None:
    if not isinstance(asset_class, CandidateAssetClass):
        raise TypeError("asset_class must be CandidateAssetClass")
    return _ASSET_FAMILY_BY_CLASS.get(asset_class)


def required_capabilities(family: AssetFamily) -> frozenset[str]:
    if not isinstance(family, AssetFamily):
        raise TypeError("family must be AssetFamily")
    return UNIVERSAL_CAPABILITIES | FAMILY_CAPABILITIES[family]


def _aware(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: object, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} cannot be empty")
    return text


@dataclass(frozen=True, slots=True)
class InstrumentCapabilityEvidence:
    """Point-in-time proofs for one exact canonical instrument.

    `capabilities` contains only capabilities that have passed their deterministic
    proof. A provider response by itself is not a proof. Every present capability
    must name a durable proof identifier in `proof_identifiers`.
    """

    instrument_identifier: str
    symbol: str
    asset_class: CandidateAssetClass
    venue: str
    country_code: str
    instrument_type: str
    observed_at: datetime
    expires_at: datetime
    capabilities: frozenset[str]
    proof_identifiers: Mapping[str, str]
    source_identifiers: tuple[str, ...]
    average_daily_dollar_volume: float
    minimum_average_daily_dollar_volume: float
    leverage_multiplier: float = 1.0
    maximum_gross_leverage: float = 1.0
    provider_authority: bool = False
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        for name in (
            "instrument_identifier",
            "symbol",
            "venue",
            "country_code",
            "instrument_type",
        ):
            _text(getattr(self, name), name=name)
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if self.asset_class is CandidateAssetClass.OTHER:
            # Keep discovery broad while remaining explicit that OTHER cannot be
            # certified by the universal paper authority.
            pass
        observed = _aware(self.observed_at, name="observed_at")
        expires = _aware(self.expires_at, name="expires_at")
        if expires <= observed:
            raise ValueError("expires_at must follow observed_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "expires_at", expires)
        if not isinstance(self.capabilities, frozenset):
            raise TypeError("capabilities must be frozenset")
        if not isinstance(self.proof_identifiers, Mapping):
            raise TypeError("proof_identifiers must be a mapping")
        normalized_proofs = {
            _text(key, name="capability"): _text(value, name="proof_identifier")
            for key, value in self.proof_identifiers.items()
        }
        missing_proofs = sorted(self.capabilities - normalized_proofs.keys())
        if missing_proofs:
            raise ValueError(
                "capabilities require durable proof identifiers: "
                + ", ".join(missing_proofs)
            )
        object.__setattr__(self, "proof_identifiers", normalized_proofs)
        sources = tuple(dict.fromkeys(_text(x, name="source_identifier") for x in self.source_identifiers))
        if not sources:
            raise ValueError("source_identifiers requires at least one source")
        object.__setattr__(self, "source_identifiers", sources)
        for name in (
            "average_daily_dollar_volume",
            "minimum_average_daily_dollar_volume",
            "leverage_multiplier",
            "maximum_gross_leverage",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if float(value) < 0.0:
                raise ValueError(f"{name} cannot be negative")
        if self.maximum_gross_leverage <= 0.0:
            raise ValueError("maximum_gross_leverage must be positive")
        if self.provider_authority:
            raise ValueError("providers cannot grant paper investment authority")
        if self.real_money_authorized:
            raise ValueError("universal capability evidence is paper-only")


@dataclass(frozen=True, slots=True)
class CapabilityEvaluation:
    instrument_identifier: str
    asset_family: AssetFamily | None
    evaluated_at: datetime
    discovered: bool
    identified: bool
    evidence_qualified: bool
    analytically_supported: bool
    lifecycle_valid: bool
    paper_executable: bool
    certifiable: bool
    missing_capabilities: tuple[str, ...]
    blockers: tuple[str, ...]
    proof_identifiers: Mapping[str, str]
    provider_authority: bool = False
    real_money_authorized: bool = False
    schema_version: str = "universal-capability-evaluation.v1"

    @property
    def highest_stage(self) -> str:
        for name in (
            "certifiable",
            "paper_executable",
            "lifecycle_valid",
            "analytically_supported",
            "evidence_qualified",
            "identified",
            "discovered",
        ):
            if bool(getattr(self, name)):
                return name
        return "unobserved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_identifier": self.instrument_identifier,
            "asset_family": self.asset_family.value if self.asset_family else None,
            "evaluated_at": self.evaluated_at.isoformat(),
            "discovered": self.discovered,
            "identified": self.identified,
            "evidence_qualified": self.evidence_qualified,
            "analytically_supported": self.analytically_supported,
            "lifecycle_valid": self.lifecycle_valid,
            "paper_executable": self.paper_executable,
            "certifiable": self.certifiable,
            "highest_stage": self.highest_stage,
            "missing_capabilities": list(self.missing_capabilities),
            "blockers": list(self.blockers),
            "proof_identifiers": dict(sorted(self.proof_identifiers.items())),
            "provider_authority": False,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }


def evaluate_capabilities(
    evidence: InstrumentCapabilityEvidence, *, evaluated_at: datetime
) -> CapabilityEvaluation:
    if not isinstance(evidence, InstrumentCapabilityEvidence):
        raise TypeError("evidence must be InstrumentCapabilityEvidence")
    timestamp = _aware(evaluated_at, name="evaluated_at")
    family = family_for_asset_class(evidence.asset_class)
    blockers: list[str] = []
    if family is None:
        blockers.append("unsupported_asset_family")
        missing: tuple[str, ...] = ()
    else:
        missing = tuple(sorted(required_capabilities(family) - evidence.capabilities))
        blockers.extend(f"missing_capability:{name}" for name in missing)
    if timestamp >= evidence.expires_at:
        blockers.append("capability_evidence_stale")
    if evidence.average_daily_dollar_volume < evidence.minimum_average_daily_dollar_volume:
        blockers.append("liquidity_below_certified_floor")
    if abs(evidence.leverage_multiplier) > evidence.maximum_gross_leverage + 1e-12:
        blockers.append("leverage_exceeds_certified_limit")

    available = evidence.capabilities
    identified = "identity" in available and timestamp < evidence.expires_at
    evidence_qualified = identified and {"market_data", "evidence"}.issubset(available)
    analytically_supported = evidence_qualified and {
        "valuation",
        "model_compatibility",
        "transaction_costs",
        "liquidity",
        "risk_controls",
    }.issubset(available)
    lifecycle_required = FAMILY_CAPABILITIES.get(family, frozenset())
    lifecycle_valid = bool(family) and analytically_supported and lifecycle_required.issubset(available)
    paper_executable = lifecycle_valid and {
        "execution_model",
        "execution_simulation",
        "accounting_treatment",
        "accounting_simulation",
        "custody_settlement",
        "portfolio_construction",
        "trading_calendar",
        "reconciliation",
    }.issubset(available)
    certifiable = paper_executable and not blockers
    return CapabilityEvaluation(
        instrument_identifier=evidence.instrument_identifier,
        asset_family=family,
        evaluated_at=timestamp,
        discovered=True,
        identified=identified,
        evidence_qualified=evidence_qualified,
        analytically_supported=analytically_supported,
        lifecycle_valid=lifecycle_valid,
        paper_executable=paper_executable,
        certifiable=certifiable,
        missing_capabilities=missing,
        blockers=tuple(dict.fromkeys(blockers)),
        proof_identifiers=evidence.proof_identifiers,
    )


def investability_coverage(
    evaluations: Iterable[CapabilityEvaluation],
    *,
    paper_certified_identifiers: Iterable[str] = (),
) -> dict[str, Any]:
    values = tuple(evaluations)
    certified = frozenset(str(value).strip() for value in paper_certified_identifiers if str(value).strip())
    identifiers = [item.instrument_identifier for item in values]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("investability coverage contains duplicate instruments")
    family_counts: dict[str, Counter[str]] = {}
    blocker_counts: Counter[str] = Counter()
    for item in values:
        family = item.asset_family.value if item.asset_family else "unsupported"
        counts = family_counts.setdefault(family, Counter())
        for stage in (
            "discovered",
            "identified",
            "evidence_qualified",
            "analytically_supported",
            "lifecycle_valid",
            "paper_executable",
            "certifiable",
        ):
            if bool(getattr(item, stage)):
                counts[stage] += 1
        for blocker in item.blockers:
            blocker_counts[blocker] += 1
    stage_totals = {
        stage: sum(bool(getattr(item, stage)) for item in values)
        for stage in (
            "discovered",
            "identified",
            "evidence_qualified",
            "analytically_supported",
            "lifecycle_valid",
            "paper_executable",
            "certifiable",
        )
    }
    stage_totals["paper_certified"] = sum(identifier in certified for identifier in identifiers)
    # Paper certification permits CIO consideration; it is not a CIO decision.
    stage_totals["cio_eligible"] = stage_totals["paper_certified"]
    evaluated_at = max((item.evaluated_at for item in values), default=datetime.now(timezone.utc))
    return {
        "schema_version": "global-investability-coverage.v1",
        "evaluated_at": evaluated_at.isoformat(),
        **stage_totals,
        "by_asset_family": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(family_counts.items())
        },
        "blockers": dict(sorted(blocker_counts.items())),
        "provider_authority": False,
        "real_money_authorized": False,
    }


__all__ = [
    "AssetFamily",
    "CapabilityEvaluation",
    "FAMILY_CAPABILITIES",
    "InstrumentCapabilityEvidence",
    "UNIVERSAL_CAPABILITIES",
    "evaluate_capabilities",
    "family_for_asset_class",
    "investability_coverage",
    "required_capabilities",
]
