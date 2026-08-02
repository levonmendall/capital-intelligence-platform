"""Append-only capability authority for universal liquid-market allocation.

Every classified liquid public-market family may compete for capital. Identity or
market-data availability alone never makes an instrument investable: a human
governance record must prove the complete asset-specific analytical, portfolio,
execution, custody, settlement, lifecycle, thesis, and evaluation stack for paper
operation. Unclassified instruments remain fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from cio.models import CandidateAssetClass, CandidateInstrument


CORE_POLICY_ASSET_CLASSES = frozenset(
    {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.US_ETF,
        CandidateAssetClass.CASH_EQUIVALENT,
    }
)

UNIVERSAL_GOVERNED_ASSET_CLASSES = frozenset(
    set(CandidateAssetClass)
    - set(CORE_POLICY_ASSET_CLASSES)
    - {CandidateAssetClass.OTHER}
)

# Backward-compatible name retained for callers while its scope is now universal.
EXPANSION_ASSET_CLASSES = UNIVERSAL_GOVERNED_ASSET_CLASSES


class AssetClassGovernanceError(RuntimeError):
    """Raised when an asset class lacks usable governed approval."""


class AssetClassGovernanceIntegrityError(AssetClassGovernanceError):
    """Raised when the append-only approval history is invalid."""


class AssetClassApprovalState(str, Enum):
    """Lifecycle state of one direct-recommendation asset-class capability."""

    EVIDENCE_ONLY = "evidence_only"
    RESEARCH_APPROVED = "research_approved"
    PAPER_ELIGIBLE = "paper_eligible"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class TradingSessionModel(str, Enum):
    """Canonical market availability pattern used by implementation controls."""

    EXCHANGE_LOCAL = "exchange_local"
    DEALER_24_5 = "dealer_24_5"
    CONTINUOUS_24_5 = "continuous_24_5"
    CONTINUOUS_24_7 = "continuous_24_7"


class CustodySettlementModel(str, Enum):
    """Approved paper-operating representation of custody and settlement risk."""

    BROKER_CUSTODIED_SECURITY = "broker_custodied_security"
    CENTRAL_SECURITIES_DEPOSITORY = "central_securities_depository"
    PRIME_BROKER_SPOT_FX = "prime_broker_spot_fx"
    QUALIFIED_DIGITAL_ASSET_CUSTODY = "qualified_digital_asset_custody"
    FUTURES_CLEARING = "futures_clearing"
    OPTIONS_CLEARING = "options_clearing"
    COLLATERALIZED_DERIVATIVE = "collateralized_derivative"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name=field_name)


def _texts(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
    uppercase: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _text(item, field_name=field_name).upper()
        if uppercase
        else _text(item, field_name=field_name)
        for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _positive_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not normalized > 0.0 or normalized == float("inf"):
        raise ValueError(f"{field_name} must be finite and positive")
    return round(normalized, 12)


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("asset-class governance payload must be finite JSON") from error


@dataclass(frozen=True, slots=True)
class AssetClassCapabilityProfile:
    """Complete instrument-family capability proof for governed paper allocation."""

    asset_class: CandidateAssetClass
    state: AssetClassApprovalState
    approved_venues: tuple[str, ...]
    approved_country_codes: tuple[str, ...]
    base_currency: str
    supported_quote_currencies: tuple[str, ...]
    trading_session_model: TradingSessionModel
    custody_settlement_model: CustodySettlementModel
    allowed_instrument_types: tuple[str, ...] = ()
    maximum_gross_leverage: float = 1.0
    identity_model_version: str | None = None
    valuation_model_version: str | None = None
    expected_return_model_version: str | None = None
    liquidity_model_version: str | None = None
    cost_model_version: str | None = None
    portfolio_risk_model_version: str | None = None
    execution_model_version: str | None = None
    thesis_model_version: str | None = None
    evaluation_model_version: str | None = None
    contract_model_version: str | None = None
    margin_model_version: str | None = None
    lifecycle_model_version: str | None = None
    roll_model_version: str | None = None
    security_master_certification_identifier: str | None = None
    market_data_certification_identifier: str | None = None
    analytical_evidence_certification_identifier: str | None = None
    execution_certification_identifier: str | None = None
    custody_settlement_identifier: str | None = None
    source_identifiers: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    schema_version: str = "asset-class-capability-profile.v2"

    def __post_init__(self) -> None:
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be a CandidateAssetClass")
        if self.asset_class not in UNIVERSAL_GOVERNED_ASSET_CLASSES:
            raise ValueError(
                "capability approval is required only for classified non-core "
                "liquid public-market families"
            )
        if not isinstance(self.state, AssetClassApprovalState):
            raise TypeError("state must be an AssetClassApprovalState")
        if not isinstance(self.trading_session_model, TradingSessionModel):
            raise TypeError("trading_session_model must be TradingSessionModel")
        if not isinstance(self.custody_settlement_model, CustodySettlementModel):
            raise TypeError("custody_settlement_model must be CustodySettlementModel")
        object.__setattr__(self, "approved_venues", _texts(self.approved_venues, field_name="approved_venues", uppercase=True))
        object.__setattr__(self, "approved_country_codes", _texts(self.approved_country_codes, field_name="approved_country_codes", uppercase=True))
        object.__setattr__(self, "base_currency", _text(self.base_currency, field_name="base_currency").upper())
        object.__setattr__(self, "supported_quote_currencies", _texts(self.supported_quote_currencies, field_name="supported_quote_currencies", uppercase=True))
        types = self.allowed_instrument_types or _default_instrument_types(self.asset_class)
        object.__setattr__(self, "allowed_instrument_types", _texts(tuple(item.lower() for item in types), field_name="allowed_instrument_types", minimum=1))
        object.__setattr__(self, "maximum_gross_leverage", _positive_number(self.maximum_gross_leverage, field_name="maximum_gross_leverage"))
        optional_fields = (
            "identity_model_version", "valuation_model_version",
            "expected_return_model_version", "liquidity_model_version",
            "cost_model_version", "portfolio_risk_model_version",
            "execution_model_version", "thesis_model_version",
            "evaluation_model_version", "contract_model_version",
            "margin_model_version", "lifecycle_model_version",
            "roll_model_version", "security_master_certification_identifier",
            "market_data_certification_identifier",
            "analytical_evidence_certification_identifier",
            "execution_certification_identifier",
            "custody_settlement_identifier",
        )
        for field_name in optional_fields:
            object.__setattr__(self, field_name, _optional_text(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "source_identifiers", _texts(self.source_identifiers, field_name="source_identifiers"))
        object.__setattr__(self, "limitations", _texts(self.limitations, field_name="limitations"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, field_name="schema_version"))
        self._validate_asset_specific_structure()
        if self.state is AssetClassApprovalState.PAPER_ELIGIBLE and self.missing_paper_capabilities:
            raise ValueError(
                "paper-eligible asset-class profile is incomplete: "
                + ", ".join(self.missing_paper_capabilities)
            )

    def _validate_asset_specific_structure(self) -> None:
        """Validate declared capabilities without an instrument-type whitelist.

        ``allowed_instrument_types`` is itself part of the human-reviewed capability
        approval.  This layer enforces the operating model implied by that declaration
        but does not require a code change for every newly certified public instrument
        structure.
        """

        types = set(self.allowed_instrument_types)
        derivative_types = {
            "future", "perpetual", "option", "forward", "swap"
        }
        listed_types = {
            "common_stock", "preferred_stock", "fund", "reit", "trust",
            "partnership", "warrant", "right",
        }

        if self.asset_class is CandidateAssetClass.CRYPTO and types <= {
            "token", "spot", "stablecoin", "perpetual", "future"
        }:
            if self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_7:
                raise ValueError(
                    "direct digital assets require the continuous 24/7 session model"
                )
            if self.custody_settlement_model not in {
                CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY,
                CustodySettlementModel.COLLATERALIZED_DERIVATIVE,
                CustodySettlementModel.FUTURES_CLEARING,
            }:
                raise ValueError(
                    "direct digital assets require certified digital custody or derivatives clearing"
                )

        if self.asset_class is CandidateAssetClass.FX and types <= {
            "spot", "forward", "swap"
        }:
            if self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_5:
                raise ValueError("direct FX requires the continuous 24/5 session model")
            if self.custody_settlement_model not in {
                CustodySettlementModel.PRIME_BROKER_SPOT_FX,
                CustodySettlementModel.COLLATERALIZED_DERIVATIVE,
            }:
                raise ValueError("direct FX requires prime-broker or derivative settlement")

        if self.asset_class is CandidateAssetClass.FIXED_INCOME and not types <= {
            "fund", "common_stock", "preferred_stock"
        }:
            if self.trading_session_model not in {
                TradingSessionModel.EXCHANGE_LOCAL,
                TradingSessionModel.DEALER_24_5,
            }:
                raise ValueError(
                    "direct fixed income requires exchange or dealer-market sessions"
                )
            if self.custody_settlement_model not in {
                CustodySettlementModel.BROKER_CUSTODIED_SECURITY,
                CustodySettlementModel.CENTRAL_SECURITIES_DEPOSITORY,
                CustodySettlementModel.COLLATERALIZED_DERIVATIVE,
            }:
                raise ValueError(
                    "direct fixed income requires broker, depository, or derivative settlement"
                )

        if types & derivative_types:
            permitted = {
                CustodySettlementModel.FUTURES_CLEARING,
                CustodySettlementModel.OPTIONS_CLEARING,
                CustodySettlementModel.COLLATERALIZED_DERIVATIVE,
                CustodySettlementModel.PRIME_BROKER_SPOT_FX,
                CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY,
            }
            if self.custody_settlement_model not in permitted:
                raise ValueError(
                    "derivative structures require a certified clearing or collateral model"
                )

        if types <= listed_types and self.asset_class not in {
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.FX,
        }:
            self._require_listed_security_structure(self.asset_class.value)

    def _require_listed_security_structure(self, label: str) -> None:
        if self.trading_session_model is not TradingSessionModel.EXCHANGE_LOCAL:
            raise ValueError(f"{label} requires local-exchange sessions")
        if self.custody_settlement_model is not CustodySettlementModel.BROKER_CUSTODIED_SECURITY:
            raise ValueError(f"{label} requires broker-custodied settlement")

    def _require_derivative_structure(
        self,
        label: str,
        permitted_custody: set[CustodySettlementModel],
    ) -> None:
        if self.trading_session_model is not TradingSessionModel.EXCHANGE_LOCAL:
            raise ValueError(f"{label} requires exchange-local sessions")
        if self.custody_settlement_model not in permitted_custody:
            raise ValueError(f"{label} requires certified derivatives clearing")

    @property
    def missing_paper_capabilities(self) -> tuple[str, ...]:
        fields = [
            "identity_model_version", "valuation_model_version",
            "expected_return_model_version", "liquidity_model_version",
            "cost_model_version", "portfolio_risk_model_version",
            "execution_model_version", "thesis_model_version",
            "evaluation_model_version",
            "security_master_certification_identifier",
            "market_data_certification_identifier",
            "analytical_evidence_certification_identifier",
            "execution_certification_identifier",
            "custody_settlement_identifier",
        ]
        derivative_types = set(self.allowed_instrument_types) & {
            "future", "perpetual", "option", "forward", "swap", "warrant", "right"
        }
        if derivative_types:
            fields.extend(("contract_model_version", "margin_model_version", "lifecycle_model_version"))
        if derivative_types & {"future", "perpetual"}:
            fields.append("roll_model_version")
        missing = [name for name in fields if getattr(self, name) is None]
        if not self.approved_venues:
            missing.append("approved_venues")
        if not self.approved_country_codes:
            missing.append("approved_country_codes")
        if not self.supported_quote_currencies:
            missing.append("supported_quote_currencies")
        if not self.allowed_instrument_types:
            missing.append("allowed_instrument_types")
        if not self.source_identifiers:
            missing.append("source_identifiers")
        return tuple(missing)

    @property
    def paper_eligible(self) -> bool:
        return self.state is AssetClassApprovalState.PAPER_ELIGIBLE and not self.missing_paper_capabilities

    def permits(self, instrument: CandidateInstrument) -> tuple[str, ...]:
        reasons: list[str] = []
        if instrument.venue not in self.approved_venues:
            reasons.append(f"venue {instrument.venue} is outside the asset-class approval")
        if instrument.country_code not in self.approved_country_codes:
            reasons.append(f"country {instrument.country_code} is outside the asset-class approval")
        if instrument.instrument_type not in self.allowed_instrument_types:
            reasons.append(f"instrument type {instrument.instrument_type} is outside the asset-class approval")
        if abs(instrument.leverage_multiplier) > self.maximum_gross_leverage + 1e-9:
            reasons.append("instrument leverage exceeds the asset-class approval")
        return tuple(reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class.value,
            "state": self.state.value,
            "approved_venues": list(self.approved_venues),
            "approved_country_codes": list(self.approved_country_codes),
            "base_currency": self.base_currency,
            "supported_quote_currencies": list(self.supported_quote_currencies),
            "trading_session_model": self.trading_session_model.value,
            "custody_settlement_model": self.custody_settlement_model.value,
            "allowed_instrument_types": list(self.allowed_instrument_types),
            "maximum_gross_leverage": self.maximum_gross_leverage,
            **{name: getattr(self, name) for name in (
                "identity_model_version", "valuation_model_version",
                "expected_return_model_version", "liquidity_model_version",
                "cost_model_version", "portfolio_risk_model_version",
                "execution_model_version", "thesis_model_version",
                "evaluation_model_version", "contract_model_version",
                "margin_model_version", "lifecycle_model_version",
                "roll_model_version", "security_master_certification_identifier",
                "market_data_certification_identifier",
                "analytical_evidence_certification_identifier",
                "execution_certification_identifier",
                "custody_settlement_identifier",
            )},
            "source_identifiers": list(self.source_identifiers),
            "limitations": list(self.limitations),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AssetClassCapabilityProfile":
        return cls(
            asset_class=CandidateAssetClass(str(payload["asset_class"])),
            state=AssetClassApprovalState(str(payload["state"])),
            approved_venues=tuple(str(item) for item in payload.get("approved_venues", ())),
            approved_country_codes=tuple(str(item) for item in payload.get("approved_country_codes", ())),
            base_currency=str(payload["base_currency"]),
            supported_quote_currencies=tuple(str(item) for item in payload.get("supported_quote_currencies", ())),
            trading_session_model=TradingSessionModel(str(payload["trading_session_model"])),
            custody_settlement_model=CustodySettlementModel(str(payload["custody_settlement_model"])),
            allowed_instrument_types=tuple(str(item) for item in payload.get("allowed_instrument_types", ())),
            maximum_gross_leverage=float(payload.get("maximum_gross_leverage", 1.0)),
            **{name: payload.get(name) for name in (
                "identity_model_version", "valuation_model_version",
                "expected_return_model_version", "liquidity_model_version",
                "cost_model_version", "portfolio_risk_model_version",
                "execution_model_version", "thesis_model_version",
                "evaluation_model_version", "contract_model_version",
                "margin_model_version", "lifecycle_model_version",
                "roll_model_version", "security_master_certification_identifier",
                "market_data_certification_identifier",
                "analytical_evidence_certification_identifier",
                "execution_certification_identifier",
                "custody_settlement_identifier",
            )},
            source_identifiers=tuple(str(item) for item in payload.get("source_identifiers", ())),
            limitations=tuple(str(item) for item in payload.get("limitations", ())),
            schema_version=str(payload.get("schema_version", "asset-class-capability-profile.v2")),
        )


def _default_instrument_types(asset_class: CandidateAssetClass) -> tuple[str, ...]:
    return {
        CandidateAssetClass.INTERNATIONAL_EQUITY: ("common_stock", "preferred_stock", "fund"),
        CandidateAssetClass.FIXED_INCOME: ("bond",),
        CandidateAssetClass.COMMODITY: ("future",),
        CandidateAssetClass.FX: ("spot",),
        CandidateAssetClass.CRYPTO: ("token", "spot", "stablecoin"),
        CandidateAssetClass.REAL_ESTATE: ("common_stock", "fund"),
        CandidateAssetClass.FUTURE: ("future", "perpetual"),
        CandidateAssetClass.OPTION: ("option",),
        CandidateAssetClass.VOLATILITY: ("future", "option"),
        CandidateAssetClass.ALTERNATIVE: ("fund", "common_stock", "spot"),
    }[asset_class]


@dataclass(frozen=True, slots=True)
class AssetClassApproval:
    """One immutable human-governance decision for an asset-class profile."""

    identifier: str
    profile: AssetClassCapabilityProfile
    approved_at: datetime
    effective_at: datetime
    expires_at: datetime
    governance_identifier: str
    process_version: str
    code_version: str
    rationale: str
    schema_version: str = "asset-class-approval.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "governance_identifier",
            "process_version",
            "code_version",
            "rationale",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.profile, AssetClassCapabilityProfile):
            raise TypeError("profile must be AssetClassCapabilityProfile")
        for field_name in ("approved_at", "effective_at", "expires_at"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.effective_at < self.approved_at:
            raise ValueError("effective_at cannot predate approved_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must follow effective_at")

    def active_at(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return self.effective_at <= resolved < self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "profile": self.profile.to_dict(),
            "approved_at": self.approved_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "governance_identifier": self.governance_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "rationale": self.rationale,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AssetClassApproval":
        profile = payload["profile"]
        if not isinstance(profile, Mapping):
            raise TypeError("profile must encode an object")
        return cls(
            identifier=str(payload["identifier"]),
            profile=AssetClassCapabilityProfile.from_dict(profile),
            approved_at=datetime.fromisoformat(str(payload["approved_at"])),
            effective_at=datetime.fromisoformat(str(payload["effective_at"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            governance_identifier=str(payload["governance_identifier"]),
            process_version=str(payload["process_version"]),
            code_version=str(payload["code_version"]),
            rationale=str(payload["rationale"]),
            schema_version=str(
                payload.get("schema_version", "asset-class-approval.v1")
            ),
        )


@dataclass(frozen=True, slots=True)
class AssetClassScopeAssessment:
    """Point-in-time direct-recommendation result for one candidate instrument."""

    instrument_id: str
    asset_class: CandidateAssetClass
    direct_recommendation_allowed: bool
    approval_identifier: str | None
    approval_state: AssetClassApprovalState | None
    policy_version: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _text(self.instrument_id, field_name="instrument_id"),
        )
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if not isinstance(self.direct_recommendation_allowed, bool):
            raise TypeError("direct_recommendation_allowed must be a bool")
        object.__setattr__(
            self,
            "approval_identifier",
            _optional_text(
                self.approval_identifier,
                field_name="approval_identifier",
            ),
        )
        if self.approval_state is not None and not isinstance(
            self.approval_state,
            AssetClassApprovalState,
        ):
            raise TypeError("approval_state must be AssetClassApprovalState")
        object.__setattr__(
            self,
            "policy_version",
            _text(self.policy_version, field_name="policy_version"),
        )
        object.__setattr__(
            self,
            "reasons",
            _texts(self.reasons, field_name="reasons", minimum=1),
        )


class SQLiteAssetClassApprovalStore:
    """Append-only, hash-chained asset-class governance authority."""

    _TABLE = "asset_class_approvals"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    asset_class TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS asset_class_approval_lookup
                ON {self._TABLE} (asset_class, effective_at, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'asset-class approvals are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'asset-class approvals are append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        asset_class: str,
        approved_at: str,
        effective_at: str,
        expires_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        value = "|".join(
            (
                str(sequence),
                event_identifier,
                asset_class,
                approved_at,
                effective_at,
                expires_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def append(self, approval: AssetClassApproval) -> int:
        if not isinstance(approval, AssetClassApproval):
            raise TypeError("approval must be AssetClassApproval")
        self.verify_integrity()
        payload_json = _canonical_json(approval.to_dict())
        values = (
            approval.identifier,
            approval.profile.asset_class.value,
            approval.approved_at.isoformat(),
            approval.effective_at.isoformat(),
            approval.expires_at.isoformat(),
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (approval.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise AssetClassGovernanceError(
                        "asset-class approval identifier already exists with "
                        "different content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = (
                self._GENESIS_HASH
                if tail is None
                else str(tail["content_hash"])
            )
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=values[0],
                asset_class=values[1],
                approved_at=values[2],
                effective_at=values[3],
                expires_at=values[4],
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, asset_class, approved_at,
                    effective_at, expires_at, payload_json, previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    *values,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def approvals(
        self,
        asset_class: CandidateAssetClass | None = None,
    ) -> tuple[AssetClassApproval, ...]:
        with self._connect() as connection:
            if asset_class is None:
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} ORDER BY sequence"
                ).fetchall()
            else:
                if not isinstance(asset_class, CandidateAssetClass):
                    raise TypeError("asset_class must be CandidateAssetClass")
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} "
                    "WHERE asset_class = ? ORDER BY sequence",
                    (asset_class.value,),
                ).fetchall()
        return tuple(
            AssetClassApproval.from_dict(json.loads(str(row["payload_json"])))
            for row in rows
        )

    def active_approvals(
        self,
        asset_class: CandidateAssetClass,
        *,
        evaluated_at: datetime,
    ) -> tuple[AssetClassApproval, ...]:
        if not isinstance(asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        return tuple(
            item for item in self.approvals(asset_class) if item.active_at(timestamp)
        )

    def active(
        self,
        asset_class: CandidateAssetClass,
        *,
        evaluated_at: datetime,
    ) -> AssetClassApproval | None:
        if not isinstance(asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        matching = self.active_approvals(
            asset_class, evaluated_at=evaluated_at
        )
        return None if not matching else matching[-1]

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise AssetClassGovernanceIntegrityError(
                    "asset-class approval sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise AssetClassGovernanceIntegrityError(
                    "asset-class approval previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                asset_class=str(row["asset_class"]),
                approved_at=str(row["approved_at"]),
                effective_at=str(row["effective_at"]),
                expires_at=str(row["expires_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise AssetClassGovernanceIntegrityError(
                    "asset-class approval content hash is invalid"
                )
            previous_hash = expected_hash
        return True


class AssetClassScopeAuthority:
    """Resolve universal governed-market recommendation eligibility at one timestamp."""

    def __init__(
        self,
        store: SQLiteAssetClassApprovalStore,
        *,
        policy_version: str = "universal-market-scope-governance.v1",
    ) -> None:
        if not isinstance(store, SQLiteAssetClassApprovalStore):
            raise TypeError("store must be SQLiteAssetClassApprovalStore")
        self.store = store
        self.policy_version = _text(policy_version, field_name="policy_version")

    def assess(self, instrument: CandidateInstrument, *, evaluated_at: datetime) -> AssetClassScopeAssessment:
        if not isinstance(instrument, CandidateInstrument):
            raise TypeError("instrument must be CandidateInstrument")
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        if instrument.asset_class not in UNIVERSAL_GOVERNED_ASSET_CLASSES:
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=False,
                approval_identifier=None,
                approval_state=None,
                policy_version=self.policy_version,
                reasons=("asset class is not a classified governed non-core liquid market",),
            )
        self.store.verify_integrity()
        approvals = self.store.active_approvals(
            instrument.asset_class, evaluated_at=timestamp
        )
        if not approvals:
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=False,
                approval_identifier=None,
                approval_state=None,
                policy_version=self.policy_version,
                reasons=("no active asset-class governance approval exists at the decision timestamp",),
            )
        for approval in reversed(approvals):
            profile = approval.profile
            structural_reasons = profile.permits(instrument)
            if structural_reasons:
                continue
            if not profile.paper_eligible:
                return AssetClassScopeAssessment(
                    instrument_id=instrument.instrument_id,
                    asset_class=instrument.asset_class,
                    direct_recommendation_allowed=False,
                    approval_identifier=approval.identifier,
                    approval_state=profile.state,
                    policy_version=self.policy_version,
                    reasons=(
                        f"asset-class approval state is {profile.state.value}, not paper_eligible",
                    ),
                )
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=True,
                approval_identifier=approval.identifier,
                approval_state=profile.state,
                policy_version=self.policy_version,
                reasons=(
                    "instrument family, structure, leverage, venue, and jurisdiction are covered by an active complete paper-eligibility approval",
                ),
            )
        latest = approvals[-1]
        reasons = ([] if latest.profile.paper_eligible else [
            f"asset-class approval state is {latest.profile.state.value}, not paper_eligible"
        ])
        reasons.extend(latest.profile.permits(instrument))
        return AssetClassScopeAssessment(
            instrument_id=instrument.instrument_id,
            asset_class=instrument.asset_class,
            direct_recommendation_allowed=False,
            approval_identifier=latest.identifier,
            approval_state=latest.profile.state,
            policy_version=self.policy_version,
            reasons=tuple(reasons) or (
                "no active structure-specific approval matches the instrument",
            ),
        )

    def require_paper_eligible(self, instrument: CandidateInstrument, *, evaluated_at: datetime) -> AssetClassScopeAssessment:
        assessment = self.assess(instrument, evaluated_at=evaluated_at)
        if not assessment.direct_recommendation_allowed:
            raise AssetClassGovernanceError("; ".join(assessment.reasons))
        return assessment


__all__ = [
    "CORE_POLICY_ASSET_CLASSES",
    "EXPANSION_ASSET_CLASSES",
    "UNIVERSAL_GOVERNED_ASSET_CLASSES",
    "AssetClassApproval",
    "AssetClassApprovalState",
    "AssetClassCapabilityProfile",
    "AssetClassGovernanceError",
    "AssetClassGovernanceIntegrityError",
    "AssetClassScopeAssessment",
    "AssetClassScopeAuthority",
    "CustodySettlementModel",
    "SQLiteAssetClassApprovalStore",
    "TradingSessionModel",
]
