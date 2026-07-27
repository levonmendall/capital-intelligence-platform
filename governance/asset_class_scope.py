"""Append-only approval authority for expanding the direct investment universe.

Identity support or available market data never makes an asset class investable by
itself. Crypto, foreign exchange, and international equities may enter the
canonical screening and CIO process only after a human governance record proves
that the complete asset-specific data, analytical, portfolio, implementation,
and evaluation stack is certified for paper operation.
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


EXPANSION_ASSET_CLASSES = frozenset(
    {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
    }
)


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
    CONTINUOUS_24_5 = "continuous_24_5"
    CONTINUOUS_24_7 = "continuous_24_7"


class CustodySettlementModel(str, Enum):
    """Approved paper-operating representation of custody and settlement risk."""

    BROKER_CUSTODIED_SECURITY = "broker_custodied_security"
    PRIME_BROKER_SPOT_FX = "prime_broker_spot_fx"
    QUALIFIED_DIGITAL_ASSET_CUSTODY = "qualified_digital_asset_custody"


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
    """Asset-specific capabilities required before paper recommendations are legal.

    A profile is intentionally broader than a provider manifest. It proves that
    the entire decision loop—not only data retrieval—has a certified model and
    operating implementation for the asset class.
    """

    asset_class: CandidateAssetClass
    state: AssetClassApprovalState
    approved_venues: tuple[str, ...]
    approved_country_codes: tuple[str, ...]
    base_currency: str
    supported_quote_currencies: tuple[str, ...]
    trading_session_model: TradingSessionModel
    custody_settlement_model: CustodySettlementModel
    identity_model_version: str | None = None
    valuation_model_version: str | None = None
    expected_return_model_version: str | None = None
    liquidity_model_version: str | None = None
    cost_model_version: str | None = None
    portfolio_risk_model_version: str | None = None
    execution_model_version: str | None = None
    thesis_model_version: str | None = None
    evaluation_model_version: str | None = None
    security_master_certification_identifier: str | None = None
    market_data_certification_identifier: str | None = None
    analytical_evidence_certification_identifier: str | None = None
    execution_certification_identifier: str | None = None
    custody_settlement_identifier: str | None = None
    source_identifiers: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    schema_version: str = "asset-class-capability-profile.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be a CandidateAssetClass")
        if self.asset_class not in EXPANSION_ASSET_CLASSES:
            raise ValueError(
                "asset-class expansion approval is limited to international "
                "equity, FX, and crypto"
            )
        if not isinstance(self.state, AssetClassApprovalState):
            raise TypeError("state must be an AssetClassApprovalState")
        if not isinstance(self.trading_session_model, TradingSessionModel):
            raise TypeError("trading_session_model must be TradingSessionModel")
        if not isinstance(self.custody_settlement_model, CustodySettlementModel):
            raise TypeError(
                "custody_settlement_model must be CustodySettlementModel"
            )
        object.__setattr__(
            self,
            "approved_venues",
            _texts(
                self.approved_venues,
                field_name="approved_venues",
                uppercase=True,
            ),
        )
        object.__setattr__(
            self,
            "approved_country_codes",
            _texts(
                self.approved_country_codes,
                field_name="approved_country_codes",
                uppercase=True,
            ),
        )
        object.__setattr__(
            self,
            "base_currency",
            _text(self.base_currency, field_name="base_currency").upper(),
        )
        object.__setattr__(
            self,
            "supported_quote_currencies",
            _texts(
                self.supported_quote_currencies,
                field_name="supported_quote_currencies",
                uppercase=True,
            ),
        )
        optional_fields = (
            "identity_model_version",
            "valuation_model_version",
            "expected_return_model_version",
            "liquidity_model_version",
            "cost_model_version",
            "portfolio_risk_model_version",
            "execution_model_version",
            "thesis_model_version",
            "evaluation_model_version",
            "security_master_certification_identifier",
            "market_data_certification_identifier",
            "analytical_evidence_certification_identifier",
            "execution_certification_identifier",
            "custody_settlement_identifier",
        )
        for field_name in optional_fields:
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "source_identifiers",
            _texts(self.source_identifiers, field_name="source_identifiers"),
        )
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, field_name="schema_version"),
        )
        self._validate_asset_specific_structure()
        if self.state is AssetClassApprovalState.PAPER_ELIGIBLE:
            missing = self.missing_paper_capabilities
            if missing:
                raise ValueError(
                    "paper-eligible asset-class profile is incomplete: "
                    + ", ".join(missing)
                )

    def _validate_asset_specific_structure(self) -> None:
        if self.asset_class is CandidateAssetClass.CRYPTO:
            if self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_7:
                raise ValueError("crypto requires the continuous 24/7 session model")
            if (
                self.custody_settlement_model
                is not CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY
            ):
                raise ValueError(
                    "crypto requires the qualified digital-asset custody model"
                )
        elif self.asset_class is CandidateAssetClass.FX:
            if self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_5:
                raise ValueError("spot FX requires the continuous 24/5 session model")
            if (
                self.custody_settlement_model
                is not CustodySettlementModel.PRIME_BROKER_SPOT_FX
            ):
                raise ValueError("FX requires the prime-broker spot-FX model")
        elif self.asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
            if self.trading_session_model is not TradingSessionModel.EXCHANGE_LOCAL:
                raise ValueError(
                    "international equities require local-exchange sessions"
                )
            if (
                self.custody_settlement_model
                is not CustodySettlementModel.BROKER_CUSTODIED_SECURITY
            ):
                raise ValueError(
                    "international equities require broker-custodied settlement"
                )

    @property
    def missing_paper_capabilities(self) -> tuple[str, ...]:
        fields = (
            "identity_model_version",
            "valuation_model_version",
            "expected_return_model_version",
            "liquidity_model_version",
            "cost_model_version",
            "portfolio_risk_model_version",
            "execution_model_version",
            "thesis_model_version",
            "evaluation_model_version",
            "security_master_certification_identifier",
            "market_data_certification_identifier",
            "analytical_evidence_certification_identifier",
            "execution_certification_identifier",
            "custody_settlement_identifier",
        )
        missing = [field_name for field_name in fields if getattr(self, field_name) is None]
        if not self.approved_venues:
            missing.append("approved_venues")
        if not self.approved_country_codes:
            missing.append("approved_country_codes")
        if not self.supported_quote_currencies:
            missing.append("supported_quote_currencies")
        if not self.source_identifiers:
            missing.append("source_identifiers")
        return tuple(missing)

    @property
    def paper_eligible(self) -> bool:
        return (
            self.state is AssetClassApprovalState.PAPER_ELIGIBLE
            and not self.missing_paper_capabilities
        )

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
            "identity_model_version": self.identity_model_version,
            "valuation_model_version": self.valuation_model_version,
            "expected_return_model_version": self.expected_return_model_version,
            "liquidity_model_version": self.liquidity_model_version,
            "cost_model_version": self.cost_model_version,
            "portfolio_risk_model_version": self.portfolio_risk_model_version,
            "execution_model_version": self.execution_model_version,
            "thesis_model_version": self.thesis_model_version,
            "evaluation_model_version": self.evaluation_model_version,
            "security_master_certification_identifier": (
                self.security_master_certification_identifier
            ),
            "market_data_certification_identifier": (
                self.market_data_certification_identifier
            ),
            "analytical_evidence_certification_identifier": (
                self.analytical_evidence_certification_identifier
            ),
            "execution_certification_identifier": (
                self.execution_certification_identifier
            ),
            "custody_settlement_identifier": self.custody_settlement_identifier,
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
            approved_country_codes=tuple(
                str(item) for item in payload.get("approved_country_codes", ())
            ),
            base_currency=str(payload["base_currency"]),
            supported_quote_currencies=tuple(
                str(item) for item in payload.get("supported_quote_currencies", ())
            ),
            trading_session_model=TradingSessionModel(
                str(payload["trading_session_model"])
            ),
            custody_settlement_model=CustodySettlementModel(
                str(payload["custody_settlement_model"])
            ),
            identity_model_version=payload.get("identity_model_version"),
            valuation_model_version=payload.get("valuation_model_version"),
            expected_return_model_version=payload.get("expected_return_model_version"),
            liquidity_model_version=payload.get("liquidity_model_version"),
            cost_model_version=payload.get("cost_model_version"),
            portfolio_risk_model_version=payload.get("portfolio_risk_model_version"),
            execution_model_version=payload.get("execution_model_version"),
            thesis_model_version=payload.get("thesis_model_version"),
            evaluation_model_version=payload.get("evaluation_model_version"),
            security_master_certification_identifier=payload.get(
                "security_master_certification_identifier"
            ),
            market_data_certification_identifier=payload.get(
                "market_data_certification_identifier"
            ),
            analytical_evidence_certification_identifier=payload.get(
                "analytical_evidence_certification_identifier"
            ),
            execution_certification_identifier=payload.get(
                "execution_certification_identifier"
            ),
            custody_settlement_identifier=payload.get("custody_settlement_identifier"),
            source_identifiers=tuple(
                str(item) for item in payload.get("source_identifiers", ())
            ),
            limitations=tuple(str(item) for item in payload.get("limitations", ())),
            schema_version=str(
                payload.get("schema_version", "asset-class-capability-profile.v1")
            ),
        )


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

    def active(
        self,
        asset_class: CandidateAssetClass,
        *,
        evaluated_at: datetime,
    ) -> AssetClassApproval | None:
        if not isinstance(asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        matching = tuple(
            item
            for item in self.approvals(asset_class)
            if item.active_at(timestamp)
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
    """Resolve expanded-market recommendation eligibility at one timestamp."""

    def __init__(
        self,
        store: SQLiteAssetClassApprovalStore,
        *,
        policy_version: str = "multi-asset-scope-governance.v1",
    ) -> None:
        if not isinstance(store, SQLiteAssetClassApprovalStore):
            raise TypeError("store must be SQLiteAssetClassApprovalStore")
        self.store = store
        self.policy_version = _text(policy_version, field_name="policy_version")

    def assess(
        self,
        instrument: CandidateInstrument,
        *,
        evaluated_at: datetime,
    ) -> AssetClassScopeAssessment:
        if not isinstance(instrument, CandidateInstrument):
            raise TypeError("instrument must be CandidateInstrument")
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        if instrument.asset_class not in EXPANSION_ASSET_CLASSES:
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=False,
                approval_identifier=None,
                approval_state=None,
                policy_version=self.policy_version,
                reasons=(
                    "asset class is outside the governed crypto, FX, and global-equity expansion",
                ),
            )
        self.store.verify_integrity()
        approval = self.store.active(
            instrument.asset_class,
            evaluated_at=timestamp,
        )
        if approval is None:
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=False,
                approval_identifier=None,
                approval_state=None,
                policy_version=self.policy_version,
                reasons=(
                    "no active asset-class governance approval exists at the decision timestamp",
                ),
            )
        profile = approval.profile
        reasons: list[str] = []
        if not profile.paper_eligible:
            reasons.append(
                f"asset-class approval state is {profile.state.value}, not paper_eligible"
            )
        if instrument.venue not in profile.approved_venues:
            reasons.append(
                f"venue {instrument.venue} is outside the asset-class approval"
            )
        if instrument.country_code not in profile.approved_country_codes:
            reasons.append(
                f"country {instrument.country_code} is outside the asset-class approval"
            )
        if reasons:
            return AssetClassScopeAssessment(
                instrument_id=instrument.instrument_id,
                asset_class=instrument.asset_class,
                direct_recommendation_allowed=False,
                approval_identifier=approval.identifier,
                approval_state=profile.state,
                policy_version=self.policy_version,
                reasons=tuple(reasons),
            )
        return AssetClassScopeAssessment(
            instrument_id=instrument.instrument_id,
            asset_class=instrument.asset_class,
            direct_recommendation_allowed=True,
            approval_identifier=approval.identifier,
            approval_state=profile.state,
            policy_version=self.policy_version,
            reasons=(
                "asset class, venue, and jurisdiction are covered by an active complete paper-eligibility approval",
            ),
        )

    def require_paper_eligible(
        self,
        instrument: CandidateInstrument,
        *,
        evaluated_at: datetime,
    ) -> AssetClassScopeAssessment:
        assessment = self.assess(instrument, evaluated_at=evaluated_at)
        if not assessment.direct_recommendation_allowed:
            raise AssetClassGovernanceError("; ".join(assessment.reasons))
        return assessment


__all__ = [
    "EXPANSION_ASSET_CLASSES",
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
