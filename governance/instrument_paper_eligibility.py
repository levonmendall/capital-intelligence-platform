"""Capability-based paper-allocation authority for individual instruments.

An instrument may become paper-allocatable only through an immutable, point-in-time
certification proving the complete operating stack required by the portfolio. A
classification, symbol, price feed, or committee opinion alone never grants
allocation authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from cio.models import CandidateAssetClass


class InstrumentPaperEligibilityError(RuntimeError):
    """Raised when an instrument lacks complete paper-allocation authority."""


class InstrumentPaperEligibilityIntegrityError(InstrumentPaperEligibilityError):
    """Raised when the append-only certification chain is invalid."""


class InstrumentPaperEligibilityState(str, Enum):
    CERTIFIED = "certified"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
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
    return value.astimezone(timezone.utc)


def _positive(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{field_name} must be finite and positive")
    return round(normalized, 12)


def _ratio(value: object, *, field_name: str) -> float:
    normalized = _positive(value, field_name=field_name)
    if normalized > 1.0:
        raise ValueError(f"{field_name} must not exceed 1.0")
    return normalized


def _instrument_value(instrument: object, *names: str) -> object | None:
    for name in names:
        if hasattr(instrument, name):
            return getattr(instrument, name)
    return None


@dataclass(frozen=True, slots=True)
class InstrumentPaperEligibilityCertification:
    """Complete proof that one liquid instrument may enter paper construction."""

    identifier: str
    instrument_identifier: str
    symbol: str
    asset_class: CandidateAssetClass
    venue: str
    country_code: str
    instrument_type: str
    state: InstrumentPaperEligibilityState
    approved_at: datetime
    effective_at: datetime
    expires_at: datetime
    minimum_average_daily_dollar_volume: float
    maximum_position_weight: float
    maximum_participation_rate: float
    maximum_gross_leverage: float
    market_data_certification_identifier: str
    identity_certification_identifier: str
    evidence_certification_identifier: str
    valuation_model_version: str
    trading_calendar_certification_identifier: str
    transaction_cost_model_version: str
    liquidity_model_version: str
    accounting_model_version: str
    execution_model_version: str
    risk_model_version: str
    portfolio_construction_model_version: str
    custody_settlement_identifier: str
    asset_class_approval_identifier: str
    governance_identifier: str
    process_version: str
    code_version: str
    source_identifiers: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    schema_version: str = "instrument-paper-eligibility-certification.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "instrument_identifier",
            "symbol",
            "venue",
            "country_code",
            "instrument_type",
            "market_data_certification_identifier",
            "identity_certification_identifier",
            "evidence_certification_identifier",
            "valuation_model_version",
            "trading_calendar_certification_identifier",
            "transaction_cost_model_version",
            "liquidity_model_version",
            "accounting_model_version",
            "execution_model_version",
            "risk_model_version",
            "portfolio_construction_model_version",
            "custody_settlement_identifier",
            "asset_class_approval_identifier",
            "governance_identifier",
            "process_version",
            "code_version",
            "schema_version",
        ):
            value = _text(getattr(self, field_name), field_name=field_name)
            if field_name in {"symbol", "venue", "country_code"}:
                value = value.upper()
            elif field_name == "instrument_type":
                value = value.lower()
            object.__setattr__(self, field_name, value)
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if self.asset_class is CandidateAssetClass.OTHER:
            raise ValueError("unclassified instruments cannot be paper-certified")
        if not isinstance(self.state, InstrumentPaperEligibilityState):
            raise TypeError("state must be InstrumentPaperEligibilityState")
        for field_name in ("approved_at", "effective_at", "expires_at"):
            object.__setattr__(
                self,
                field_name,
                _aware(getattr(self, field_name), field_name=field_name),
            )
        if self.effective_at < self.approved_at:
            raise ValueError("effective_at cannot predate approved_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must follow effective_at")
        object.__setattr__(
            self,
            "minimum_average_daily_dollar_volume",
            _positive(
                self.minimum_average_daily_dollar_volume,
                field_name="minimum_average_daily_dollar_volume",
            ),
        )
        object.__setattr__(
            self,
            "maximum_position_weight",
            _ratio(self.maximum_position_weight, field_name="maximum_position_weight"),
        )
        object.__setattr__(
            self,
            "maximum_participation_rate",
            _ratio(
                self.maximum_participation_rate,
                field_name="maximum_participation_rate",
            ),
        )
        object.__setattr__(
            self,
            "maximum_gross_leverage",
            _positive(self.maximum_gross_leverage, field_name="maximum_gross_leverage"),
        )
        object.__setattr__(
            self,
            "source_identifiers",
            _texts(self.source_identifiers, field_name="source_identifiers", minimum=1),
        )
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )

    @property
    def complete_capability_identifiers(self) -> tuple[str, ...]:
        return (
            self.market_data_certification_identifier,
            self.identity_certification_identifier,
            self.evidence_certification_identifier,
            self.valuation_model_version,
            self.trading_calendar_certification_identifier,
            self.transaction_cost_model_version,
            self.liquidity_model_version,
            self.accounting_model_version,
            self.execution_model_version,
            self.risk_model_version,
            self.portfolio_construction_model_version,
            self.custody_settlement_identifier,
            self.asset_class_approval_identifier,
        )

    def active_at(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return (
            self.state is InstrumentPaperEligibilityState.CERTIFIED
            and self.effective_at <= resolved < self.expires_at
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "instrument_identifier": self.instrument_identifier,
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "venue": self.venue,
            "country_code": self.country_code,
            "instrument_type": self.instrument_type,
            "state": self.state.value,
            "approved_at": self.approved_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "minimum_average_daily_dollar_volume": self.minimum_average_daily_dollar_volume,
            "maximum_position_weight": self.maximum_position_weight,
            "maximum_participation_rate": self.maximum_participation_rate,
            "maximum_gross_leverage": self.maximum_gross_leverage,
            **{
                name: getattr(self, name)
                for name in (
                    "market_data_certification_identifier",
                    "identity_certification_identifier",
                    "evidence_certification_identifier",
                    "valuation_model_version",
                    "trading_calendar_certification_identifier",
                    "transaction_cost_model_version",
                    "liquidity_model_version",
                    "accounting_model_version",
                    "execution_model_version",
                    "risk_model_version",
                    "portfolio_construction_model_version",
                    "custody_settlement_identifier",
                    "asset_class_approval_identifier",
                    "governance_identifier",
                    "process_version",
                    "code_version",
                )
            },
            "source_identifiers": list(self.source_identifiers),
            "limitations": list(self.limitations),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "InstrumentPaperEligibilityCertification":
        return cls(
            identifier=str(payload["identifier"]),
            instrument_identifier=str(payload["instrument_identifier"]),
            symbol=str(payload["symbol"]),
            asset_class=CandidateAssetClass(str(payload["asset_class"])),
            venue=str(payload["venue"]),
            country_code=str(payload["country_code"]),
            instrument_type=str(payload["instrument_type"]),
            state=InstrumentPaperEligibilityState(str(payload["state"])),
            approved_at=datetime.fromisoformat(str(payload["approved_at"])),
            effective_at=datetime.fromisoformat(str(payload["effective_at"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            minimum_average_daily_dollar_volume=float(
                payload["minimum_average_daily_dollar_volume"]
            ),
            maximum_position_weight=float(payload["maximum_position_weight"]),
            maximum_participation_rate=float(payload["maximum_participation_rate"]),
            maximum_gross_leverage=float(payload["maximum_gross_leverage"]),
            **{
                name: str(payload[name])
                for name in (
                    "market_data_certification_identifier",
                    "identity_certification_identifier",
                    "evidence_certification_identifier",
                    "valuation_model_version",
                    "trading_calendar_certification_identifier",
                    "transaction_cost_model_version",
                    "liquidity_model_version",
                    "accounting_model_version",
                    "execution_model_version",
                    "risk_model_version",
                    "portfolio_construction_model_version",
                    "custody_settlement_identifier",
                    "asset_class_approval_identifier",
                    "governance_identifier",
                    "process_version",
                    "code_version",
                )
            },
            source_identifiers=tuple(
                str(item) for item in payload.get("source_identifiers", ())
            ),
            limitations=tuple(str(item) for item in payload.get("limitations", ())),
            schema_version=str(
                payload.get(
                    "schema_version",
                    "instrument-paper-eligibility-certification.v1",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class InstrumentPaperEligibilityAssessment:
    instrument_identifier: str
    paper_allocatable: bool
    certification_identifier: str | None
    state: InstrumentPaperEligibilityState | None
    maximum_position_weight: float | None
    reasons: tuple[str, ...]
    policy_version: str


class SQLiteInstrumentPaperEligibilityStore:
    """Append-only, hash-chained individual-instrument certification authority."""

    _TABLE = "instrument_paper_eligibility_certifications"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    instrument_identifier TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS instrument_paper_eligibility_lookup
                ON {self._TABLE} (instrument_identifier, effective_at, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'instrument paper eligibility is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'instrument paper eligibility is append-only'); END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _hash(
        *,
        sequence: int,
        event_identifier: str,
        instrument_identifier: str,
        effective_at: str,
        expires_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        value = "|".join(
            (
                str(sequence),
                event_identifier,
                instrument_identifier,
                effective_at,
                expires_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def append(self, certification: InstrumentPaperEligibilityCertification) -> int:
        if not isinstance(certification, InstrumentPaperEligibilityCertification):
            raise TypeError(
                "certification must be InstrumentPaperEligibilityCertification"
            )
        payload_json = json.dumps(
            certification.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (certification.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError(
                        "certification identifier already exists with different content"
                    )
                return int(existing["sequence"])
            row = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if row is None else int(row["sequence"]) + 1
            previous_hash = (
                self._GENESIS_HASH if row is None else str(row["content_hash"])
            )
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=certification.identifier,
                instrument_identifier=certification.instrument_identifier,
                effective_at=certification.effective_at.isoformat(),
                expires_at=certification.expires_at.isoformat(),
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    certification.identifier,
                    certification.instrument_identifier,
                    certification.effective_at.isoformat(),
                    certification.expires_at.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def certifications(
        self, instrument_identifier: str | None = None
    ) -> tuple[InstrumentPaperEligibilityCertification, ...]:
        with self._connect() as connection:
            if instrument_identifier is None:
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} ORDER BY sequence"
                ).fetchall()
            else:
                identifier = _text(
                    instrument_identifier, field_name="instrument_identifier"
                )
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} "
                    "WHERE instrument_identifier = ? ORDER BY sequence",
                    (identifier,),
                ).fetchall()
        return tuple(
            InstrumentPaperEligibilityCertification.from_dict(
                json.loads(str(row["payload_json"]))
            )
            for row in rows
        )

    def active(
        self, instrument_identifier: str, *, evaluated_at: datetime
    ) -> InstrumentPaperEligibilityCertification | None:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        matching = tuple(
            item
            for item in self.certifications(instrument_identifier)
            if item.effective_at <= timestamp < item.expires_at
        )
        if not matching:
            return None
        latest = matching[-1]
        return latest if latest.active_at(timestamp) else None

    def active_identifiers(self, *, evaluated_at: datetime) -> frozenset[str]:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        identifiers = {
            item.instrument_identifier for item in self.certifications()
        }
        return frozenset(
            identifier
            for identifier in identifiers
            if self.active(identifier, evaluated_at=timestamp) is not None
        )

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise InstrumentPaperEligibilityIntegrityError(
                    "instrument certification sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise InstrumentPaperEligibilityIntegrityError(
                    "instrument certification previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                instrument_identifier=str(row["instrument_identifier"]),
                effective_at=str(row["effective_at"]),
                expires_at=str(row["expires_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise InstrumentPaperEligibilityIntegrityError(
                    "instrument certification content hash is invalid"
                )
            previous_hash = expected_hash
        return True


class InstrumentPaperEligibilityAuthority:
    """Resolve exact, current, capability-based paper ownership eligibility."""

    def __init__(
        self,
        store: SQLiteInstrumentPaperEligibilityStore,
        *,
        policy_version: str = "capability-based-paper-eligibility.v1",
    ) -> None:
        if not isinstance(store, SQLiteInstrumentPaperEligibilityStore):
            raise TypeError("store must be SQLiteInstrumentPaperEligibilityStore")
        self.store = store
        self.policy_version = _text(policy_version, field_name="policy_version")

    def active_identifiers(self, *, evaluated_at: datetime) -> frozenset[str]:
        self.store.verify_integrity()
        return self.store.active_identifiers(evaluated_at=evaluated_at)

    def assess(
        self, instrument: object, *, evaluated_at: datetime
    ) -> InstrumentPaperEligibilityAssessment:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        identifier_value = _instrument_value(
            instrument, "instrument_id", "instrument_identifier"
        )
        identifier = _text(identifier_value, field_name="instrument_identifier")
        self.store.verify_integrity()
        certification = self.store.active(identifier, evaluated_at=timestamp)
        if certification is None:
            return InstrumentPaperEligibilityAssessment(
                instrument_identifier=identifier,
                paper_allocatable=False,
                certification_identifier=None,
                state=None,
                maximum_position_weight=None,
                reasons=(
                    "no active complete instrument paper-eligibility certification exists",
                ),
                policy_version=self.policy_version,
            )

        reasons: list[str] = []
        symbol = str(_instrument_value(instrument, "symbol") or "").strip().upper()
        venue = str(_instrument_value(instrument, "venue") or "").strip().upper()
        country = str(
            _instrument_value(instrument, "country_code") or ""
        ).strip().upper()
        instrument_type = str(
            _instrument_value(instrument, "instrument_type") or ""
        ).strip().lower()
        asset_class = _instrument_value(
            instrument, "asset_class", "execution_asset_class"
        )
        if symbol != certification.symbol:
            reasons.append("symbol does not match the certification")
        if asset_class is not certification.asset_class:
            reasons.append("asset class does not match the certification")
        if venue != certification.venue:
            reasons.append("venue does not match the certification")
        if country != certification.country_code:
            reasons.append("country does not match the certification")
        if instrument_type != certification.instrument_type:
            reasons.append("instrument type does not match the certification")

        adv = _instrument_value(instrument, "average_daily_dollar_volume")
        if isinstance(adv, bool) or not isinstance(adv, (int, float)):
            reasons.append("current average daily dollar volume is unavailable")
        elif not isfinite(float(adv)) or float(adv) < (
            certification.minimum_average_daily_dollar_volume
        ):
            reasons.append("current liquidity is below the certified floor")

        leverage = _instrument_value(instrument, "leverage_multiplier")
        resolved_leverage = 1.0 if leverage is None else float(leverage)
        if not isfinite(resolved_leverage) or abs(resolved_leverage) > (
            certification.maximum_gross_leverage + 1e-9
        ):
            reasons.append("instrument leverage exceeds the certified limit")

        return InstrumentPaperEligibilityAssessment(
            instrument_identifier=identifier,
            paper_allocatable=not reasons,
            certification_identifier=certification.identifier,
            state=certification.state,
            maximum_position_weight=certification.maximum_position_weight,
            reasons=tuple(reasons)
            or (
                "identity, market data, evidence, valuation, calendar, liquidity, "
                "cost, accounting, execution, construction, custody, and risk "
                "capabilities are actively certified",
            ),
            policy_version=self.policy_version,
        )

    def require_paper_allocatable(
        self, instrument: object, *, evaluated_at: datetime
    ) -> InstrumentPaperEligibilityAssessment:
        assessment = self.assess(instrument, evaluated_at=evaluated_at)
        if not assessment.paper_allocatable:
            raise InstrumentPaperEligibilityError("; ".join(assessment.reasons))
        return assessment


__all__ = [
    "InstrumentPaperEligibilityAssessment",
    "InstrumentPaperEligibilityAuthority",
    "InstrumentPaperEligibilityCertification",
    "InstrumentPaperEligibilityError",
    "InstrumentPaperEligibilityIntegrityError",
    "InstrumentPaperEligibilityState",
    "SQLiteInstrumentPaperEligibilityStore",
]
