"""Human-governed investment-process freeze and controlled paper-test entry.

The repository may prove that one immutable baseline is eligible for a controlled
paper test, but only a distinct human release authority may approve that exact
eligibility package for a named cohort. Development remains open on later commits.
No record in this module can authorize real money, broker connectivity, or
performance claims.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from governance.product_readiness import (
    ProductTestReadiness,
    ProductTestReadinessReport,
)
from governance.stage_binding_approval import StageBindingApproval
from operations.paper_test_campaign import (
    PaperTestCampaignBaseline,
    PaperTestCampaignReport,
    PaperTestCampaignState,
)
from operations.recovery_drill import RecoveryDrillReport, RecoveryDrillStatus


class PaperTestEntryGovernanceError(RuntimeError):
    """Raised when process-freeze or entry governance fails closed."""


class PaperTestEntryIntegrityError(PaperTestEntryGovernanceError):
    """Raised when the append-only governance chain is invalid."""


class ProcessFreezeState(str, Enum):
    FROZEN = "frozen"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class PaperTestEligibilityState(str, Enum):
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"


class PaperTestEntryDecisionState(str, Enum):
    APPROVED = "approved"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class PaperTestGovernanceEventType(str, Enum):
    PROCESS_FREEZE = "process_freeze"
    ELIGIBILITY_PACKAGE = "eligibility_package"
    ENTRY_DECISION = "entry_decision"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
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
    return value


def _digest(value: object, *, field_name: str) -> str:
    normalized = _text(value, field_name=field_name).lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_process_bundle_sha256(paths: Iterable[str | Path]) -> str:
    """Hash a reviewed process bundle using names and exact file bytes."""

    entries: list[tuple[str, str]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise PaperTestEntryGovernanceError(
                f"process bundle file is unavailable: {path}"
            )
        entries.append(
            (
                path.as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    if not entries:
        raise ValueError("process bundle requires at least one file")
    return hashlib.sha256(
        _canonical_json({"files": sorted(entries)}).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class InvestmentProcessFreeze:
    """One human-governed freeze of the process used by a test baseline."""

    identifier: str
    state: ProcessFreezeState
    recorded_at: datetime
    effective_at: datetime
    expires_at: datetime
    baseline_identifier: str
    process_version: str
    code_version: str
    process_bundle_sha256: str
    operation_plan_sha256: str
    stage_bindings_sha256: str
    configuration_sha256: str
    data_manifest_identifier: str
    governance_identifier: str
    approver_role: str
    independent_validation_identifier: str
    evidence_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]
    development_open: bool = True
    schema_version: str = "investment-process-freeze.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "data_manifest_identifier",
            "governance_identifier",
            "approver_role",
            "independent_validation_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.state, ProcessFreezeState):
            raise TypeError("state must be ProcessFreezeState")
        for field_name in ("recorded_at", "effective_at", "expires_at"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.effective_at < self.recorded_at:
            raise ValueError("effective_at cannot predate recorded_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must follow effective_at")
        for field_name in (
            "process_bundle_sha256",
            "operation_plan_sha256",
            "stage_bindings_sha256",
            "configuration_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _digest(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations", minimum=1),
        )
        if self.approver_role != "investment_process_governance":
            raise ValueError(
                "process freeze requires the investment_process_governance role"
            )
        if self.governance_identifier == self.independent_validation_identifier:
            raise ValueError("process freeze requires independent validation")
        if self.development_open is not True:
            raise ValueError("normal development must remain open")
        if self.schema_version != "investment-process-freeze.v1":
            raise ValueError("unsupported process-freeze schema")

    def active_at(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return (
            self.state is ProcessFreezeState.FROZEN
            and self.effective_at <= resolved < self.expires_at
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "state": self.state.value,
            "recorded_at": self.recorded_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "process_bundle_sha256": self.process_bundle_sha256,
            "operation_plan_sha256": self.operation_plan_sha256,
            "stage_bindings_sha256": self.stage_bindings_sha256,
            "configuration_sha256": self.configuration_sha256,
            "data_manifest_identifier": self.data_manifest_identifier,
            "governance_identifier": self.governance_identifier,
            "approver_role": self.approver_role,
            "independent_validation_identifier": (
                self.independent_validation_identifier
            ),
            "evidence_identifiers": list(self.evidence_identifiers),
            "limitations": list(self.limitations),
            "development_open": True,
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "performance_claims_permitted": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvestmentProcessFreeze":
        for prohibited in (
            "paper_test_authorized",
            "real_money_authorized",
            "performance_claims_permitted",
        ):
            if bool(value.get(prohibited, False)):
                raise ValueError(f"process freeze cannot set {prohibited}")
        return cls(
            identifier=str(value["identifier"]),
            state=ProcessFreezeState(str(value["state"])),
            recorded_at=datetime.fromisoformat(str(value["recorded_at"])),
            effective_at=datetime.fromisoformat(str(value["effective_at"])),
            expires_at=datetime.fromisoformat(str(value["expires_at"])),
            baseline_identifier=str(value["baseline_identifier"]),
            process_version=str(value["process_version"]),
            code_version=str(value["code_version"]),
            process_bundle_sha256=str(value["process_bundle_sha256"]),
            operation_plan_sha256=str(value["operation_plan_sha256"]),
            stage_bindings_sha256=str(value["stage_bindings_sha256"]),
            configuration_sha256=str(value["configuration_sha256"]),
            data_manifest_identifier=str(value["data_manifest_identifier"]),
            governance_identifier=str(value["governance_identifier"]),
            approver_role=str(value["approver_role"]),
            independent_validation_identifier=str(
                value["independent_validation_identifier"]
            ),
            evidence_identifiers=tuple(
                str(item) for item in value["evidence_identifiers"]
            ),
            limitations=tuple(str(item) for item in value["limitations"]),
            development_open=bool(value.get("development_open", True)),
            schema_version=str(
                value.get("schema_version", "investment-process-freeze.v1")
            ),
        )


@dataclass(frozen=True, slots=True)
class ControlledPaperTestEligibilityPackage:
    """Repository-assembled evidence package for one exact baseline."""

    identifier: str
    assembled_at: datetime
    state: PaperTestEligibilityState
    baseline_identifier: str
    process_version: str
    code_version: str
    process_freeze_identifier: str
    readiness_report_identifier: str
    campaign_report_identifier: str
    recovery_report_identifier: str
    stage_binding_approval_identifier: str
    blockers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    development_open: bool = True
    schema_version: str = "controlled-paper-test-eligibility.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "process_freeze_identifier",
            "readiness_report_identifier",
            "campaign_report_identifier",
            "recovery_report_identifier",
            "stage_binding_approval_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.assembled_at, field_name="assembled_at")
        if not isinstance(self.state, PaperTestEligibilityState):
            raise TypeError("state must be PaperTestEligibilityState")
        object.__setattr__(
            self,
            "blockers",
            _texts(self.blockers, field_name="blockers"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )
        if self.state is PaperTestEligibilityState.ELIGIBLE and self.blockers:
            raise ValueError("eligible package cannot contain blockers")
        if self.state is PaperTestEligibilityState.BLOCKED and not self.blockers:
            raise ValueError("blocked package requires blockers")
        if self.development_open is not True:
            raise ValueError("development must remain open")
        if self.schema_version != "controlled-paper-test-eligibility.v1":
            raise ValueError("unsupported eligibility-package schema")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "assembled_at": self.assembled_at.isoformat(),
            "state": self.state.value,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "process_freeze_identifier": self.process_freeze_identifier,
            "readiness_report_identifier": self.readiness_report_identifier,
            "campaign_report_identifier": self.campaign_report_identifier,
            "recovery_report_identifier": self.recovery_report_identifier,
            "stage_binding_approval_identifier": (
                self.stage_binding_approval_identifier
            ),
            "blockers": list(self.blockers),
            "evidence_identifiers": list(self.evidence_identifiers),
            "development_open": True,
            "eligibility_fingerprint": self._fingerprint_payload(),
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "performance_claims_permitted": False,
            "schema_version": self.schema_version,
        }

    def _fingerprint_payload(self) -> str:
        payload = {
            "identifier": self.identifier,
            "assembled_at": self.assembled_at.isoformat(),
            "state": self.state.value,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "process_freeze_identifier": self.process_freeze_identifier,
            "readiness_report_identifier": self.readiness_report_identifier,
            "campaign_report_identifier": self.campaign_report_identifier,
            "recovery_report_identifier": self.recovery_report_identifier,
            "stage_binding_approval_identifier": self.stage_binding_approval_identifier,
            "blockers": list(self.blockers),
            "evidence_identifiers": list(self.evidence_identifiers),
            "development_open": True,
            "schema_version": self.schema_version,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "ControlledPaperTestEligibilityPackage":
        for prohibited in (
            "paper_test_authorized",
            "real_money_authorized",
            "performance_claims_permitted",
        ):
            if bool(value.get(prohibited, False)):
                raise ValueError(f"eligibility package cannot set {prohibited}")
        result = cls(
            identifier=str(value["identifier"]),
            assembled_at=datetime.fromisoformat(str(value["assembled_at"])),
            state=PaperTestEligibilityState(str(value["state"])),
            baseline_identifier=str(value["baseline_identifier"]),
            process_version=str(value["process_version"]),
            code_version=str(value["code_version"]),
            process_freeze_identifier=str(value["process_freeze_identifier"]),
            readiness_report_identifier=str(value["readiness_report_identifier"]),
            campaign_report_identifier=str(value["campaign_report_identifier"]),
            recovery_report_identifier=str(value["recovery_report_identifier"]),
            stage_binding_approval_identifier=str(
                value["stage_binding_approval_identifier"]
            ),
            blockers=tuple(str(item) for item in value.get("blockers", ())),
            evidence_identifiers=tuple(
                str(item) for item in value["evidence_identifiers"]
            ),
            development_open=bool(value.get("development_open", True)),
            schema_version=str(
                value.get(
                    "schema_version",
                    "controlled-paper-test-eligibility.v1",
                )
            ),
        )
        expected = value.get("eligibility_fingerprint")
        if expected is not None and str(expected) != result._fingerprint_payload():
            raise ValueError("eligibility package fingerprint is invalid")
        return result


@dataclass(frozen=True, slots=True)
class ControlledPaperTestEntryDecision:
    """Human release decision for one exact eligibility package and cohort."""

    identifier: str
    state: PaperTestEntryDecisionState
    decided_at: datetime
    effective_at: datetime
    expires_at: datetime
    package_identifier: str
    package_fingerprint: str
    baseline_identifier: str
    process_version: str
    code_version: str
    cohort_identifier: str
    governance_identifier: str
    approver_role: str
    independent_validator_identifier: str
    rationale: str
    limitations: tuple[str, ...]
    schema_version: str = "controlled-paper-test-entry-decision.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "package_identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "cohort_identifier",
            "governance_identifier",
            "approver_role",
            "independent_validator_identifier",
            "rationale",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "package_fingerprint",
            _digest(self.package_fingerprint, field_name="package_fingerprint"),
        )
        if not isinstance(self.state, PaperTestEntryDecisionState):
            raise TypeError("state must be PaperTestEntryDecisionState")
        for field_name in ("decided_at", "effective_at", "expires_at"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.effective_at < self.decided_at:
            raise ValueError("effective_at cannot predate decided_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must follow effective_at")
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations", minimum=1),
        )
        if self.approver_role != "paper_test_release_authority":
            raise ValueError(
                "entry decision requires the paper_test_release_authority role"
            )
        if self.governance_identifier == self.independent_validator_identifier:
            raise ValueError("entry decision requires independent validation")
        if self.schema_version != "controlled-paper-test-entry-decision.v1":
            raise ValueError("unsupported entry-decision schema")

    def active_at(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return (
            self.state is PaperTestEntryDecisionState.APPROVED
            and self.effective_at <= resolved < self.expires_at
        )

    @property
    def controlled_paper_test_authorized(self) -> bool:
        return self.state is PaperTestEntryDecisionState.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "state": self.state.value,
            "decided_at": self.decided_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "package_identifier": self.package_identifier,
            "package_fingerprint": self.package_fingerprint,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "cohort_identifier": self.cohort_identifier,
            "governance_identifier": self.governance_identifier,
            "approver_role": self.approver_role,
            "independent_validator_identifier": (
                self.independent_validator_identifier
            ),
            "rationale": self.rationale,
            "limitations": list(self.limitations),
            "development_open": True,
            "controlled_paper_test_authorized": (
                self.controlled_paper_test_authorized
            ),
            "paper_only": True,
            "real_money_authorized": False,
            "broker_connectivity_authorized": False,
            "performance_claims_permitted": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "ControlledPaperTestEntryDecision":
        for prohibited in (
            "real_money_authorized",
            "broker_connectivity_authorized",
            "performance_claims_permitted",
        ):
            if bool(value.get(prohibited, False)):
                raise ValueError(f"entry decision cannot set {prohibited}")
        return cls(
            identifier=str(value["identifier"]),
            state=PaperTestEntryDecisionState(str(value["state"])),
            decided_at=datetime.fromisoformat(str(value["decided_at"])),
            effective_at=datetime.fromisoformat(str(value["effective_at"])),
            expires_at=datetime.fromisoformat(str(value["expires_at"])),
            package_identifier=str(value["package_identifier"]),
            package_fingerprint=str(value["package_fingerprint"]),
            baseline_identifier=str(value["baseline_identifier"]),
            process_version=str(value["process_version"]),
            code_version=str(value["code_version"]),
            cohort_identifier=str(value["cohort_identifier"]),
            governance_identifier=str(value["governance_identifier"]),
            approver_role=str(value["approver_role"]),
            independent_validator_identifier=str(
                value["independent_validator_identifier"]
            ),
            rationale=str(value["rationale"]),
            limitations=tuple(str(item) for item in value["limitations"]),
            schema_version=str(
                value.get(
                    "schema_version",
                    "controlled-paper-test-entry-decision.v1",
                )
            ),
        )


class PaperTestEntryPackageAssembler:
    """Combine immutable authorities without granting human approval."""

    def assemble(
        self,
        *,
        freeze: InvestmentProcessFreeze,
        readiness: ProductTestReadinessReport,
        baseline: PaperTestCampaignBaseline,
        campaign: PaperTestCampaignReport,
        recovery: RecoveryDrillReport,
        stage_binding_approval: StageBindingApproval,
        assembled_at: datetime,
    ) -> ControlledPaperTestEligibilityPackage:
        timestamp = _aware(assembled_at, field_name="assembled_at")
        blockers: list[str] = []
        if not freeze.active_at(timestamp):
            blockers.append("investment process freeze is not active")
        if freeze.baseline_identifier != baseline.identifier:
            blockers.append("process freeze and campaign baseline do not match")
        if freeze.process_version != baseline.process_version:
            blockers.append("process freeze and campaign process versions do not match")
        if freeze.code_version != baseline.code_version:
            blockers.append("process freeze and campaign code versions do not match")
        if freeze.operation_plan_sha256 != baseline.operation_plan_hash:
            blockers.append("operation-plan digest does not match the frozen baseline")
        if freeze.stage_bindings_sha256 != baseline.stage_bindings_hash:
            blockers.append("stage-binding digest does not match the frozen baseline")
        if freeze.configuration_sha256 != baseline.configuration_hash:
            blockers.append("configuration digest does not match the frozen baseline")
        if freeze.data_manifest_identifier != baseline.data_manifest_identifier:
            blockers.append("data manifest does not match the frozen baseline")
        if readiness.state is not ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST:
            blockers.append("canonical product-test readiness is not satisfied")
        if readiness.baseline_identifier != baseline.identifier:
            blockers.append("readiness report belongs to another baseline")
        if readiness.process_version != baseline.process_version:
            blockers.append("readiness report uses another process version")
        if campaign.state is not PaperTestCampaignState.SATISFIED:
            blockers.append("burn-in and failure campaign is not satisfied")
        if campaign.baseline_identifier != baseline.identifier:
            blockers.append("campaign report belongs to another baseline")
        if campaign.baseline_fingerprint != baseline.fingerprint:
            blockers.append("campaign report baseline fingerprint is invalid")
        if recovery.status is not RecoveryDrillStatus.PASSED:
            blockers.append("canonical recovery drill is not passing")
        for field_name in (
            "baseline_identifier",
            "process_version",
            "code_version",
        ):
            if getattr(recovery, field_name) != getattr(freeze, field_name):
                blockers.append(f"recovery drill {field_name} does not match freeze")
        if not stage_binding_approval.active_at(timestamp):
            blockers.append("stage-binding approval is not active")
        for field_name in (
            "baseline_identifier",
            "process_version",
            "code_version",
        ):
            if getattr(stage_binding_approval, field_name) != getattr(
                freeze,
                field_name,
            ):
                blockers.append(f"stage-binding approval {field_name} does not match")
        if stage_binding_approval.binding_sha256 != freeze.stage_bindings_sha256:
            blockers.append("stage-binding approval digest does not match freeze")
        blockers = sorted(set(blockers))
        evidence = tuple(
            dict.fromkeys(
                (
                    freeze.identifier,
                    readiness.identifier,
                    baseline.identifier,
                    campaign.identifier,
                    recovery.identifier,
                    stage_binding_approval.identifier,
                    *freeze.evidence_identifiers,
                    *readiness.evidence_identifiers,
                    *campaign.evidence_identifiers,
                    *recovery.evidence_identifiers,
                )
            )
        )
        state = (
            PaperTestEligibilityState.ELIGIBLE
            if not blockers
            else PaperTestEligibilityState.BLOCKED
        )
        return ControlledPaperTestEligibilityPackage(
            identifier=(
                f"paper-test-eligibility:{baseline.identifier}:"
                f"{timestamp.isoformat()}"
            ),
            assembled_at=timestamp,
            state=state,
            baseline_identifier=baseline.identifier,
            process_version=baseline.process_version,
            code_version=baseline.code_version,
            process_freeze_identifier=freeze.identifier,
            readiness_report_identifier=readiness.identifier,
            campaign_report_identifier=campaign.identifier,
            recovery_report_identifier=recovery.identifier,
            stage_binding_approval_identifier=stage_binding_approval.identifier,
            blockers=tuple(blockers),
            evidence_identifiers=evidence,
        )


class SQLitePaperTestEntryGovernanceStore:
    """Append-only authority for freezes, packages, and human decisions."""

    _TABLE = "paper_test_entry_governance_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    baseline_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS paper_test_entry_governance_lookup
                ON {self._TABLE}(baseline_identifier,event_type,sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper-test entry governance is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper-test entry governance is append-only'); END;
                """
            )

    @staticmethod
    def _hash(
        sequence: int,
        identifier: str,
        baseline_identifier: str,
        event_type: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    str(sequence),
                    identifier,
                    baseline_identifier,
                    event_type,
                    occurred_at,
                    payload_json,
                    previous_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

    def _append(
        self,
        *,
        identifier: str,
        baseline_identifier: str,
        event_type: PaperTestGovernanceEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> int:
        payload_json = _canonical_json(payload)
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        self.verify_integrity()
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence,event_type,payload_json FROM {self._TABLE} "
                "WHERE identifier=?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["event_type"]) != event_type.value
                    or str(existing["payload_json"]) != payload_json
                ):
                    raise PaperTestEntryGovernanceError(
                        "governance identifier has conflicting content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence,content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous = self._GENESIS if tail is None else str(tail["content_hash"])
            content_hash = self._hash(
                sequence,
                identifier,
                baseline_identifier,
                event_type.value,
                timestamp,
                payload_json,
                previous,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?,?,?)",
                (
                    sequence,
                    identifier,
                    baseline_identifier,
                    event_type.value,
                    timestamp,
                    payload_json,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def append_freeze(self, value: InvestmentProcessFreeze) -> int:
        if not isinstance(value, InvestmentProcessFreeze):
            raise TypeError("value must be InvestmentProcessFreeze")
        return self._append(
            identifier=value.identifier,
            baseline_identifier=value.baseline_identifier,
            event_type=PaperTestGovernanceEventType.PROCESS_FREEZE,
            occurred_at=value.recorded_at,
            payload=value.to_dict(),
        )

    def append_package(self, value: ControlledPaperTestEligibilityPackage) -> int:
        if not isinstance(value, ControlledPaperTestEligibilityPackage):
            raise TypeError("value must be ControlledPaperTestEligibilityPackage")
        return self._append(
            identifier=value.identifier,
            baseline_identifier=value.baseline_identifier,
            event_type=PaperTestGovernanceEventType.ELIGIBILITY_PACKAGE,
            occurred_at=value.assembled_at,
            payload=value.to_dict(),
        )

    def append_decision(
        self,
        value: ControlledPaperTestEntryDecision,
        *,
        package: ControlledPaperTestEligibilityPackage,
    ) -> int:
        if not isinstance(value, ControlledPaperTestEntryDecision):
            raise TypeError("value must be ControlledPaperTestEntryDecision")
        if not isinstance(package, ControlledPaperTestEligibilityPackage):
            raise TypeError("package must be ControlledPaperTestEligibilityPackage")
        if value.package_identifier != package.identifier:
            raise PaperTestEntryGovernanceError(
                "entry decision references another eligibility package"
            )
        if value.package_fingerprint != package.fingerprint:
            raise PaperTestEntryGovernanceError(
                "entry decision package fingerprint does not match"
            )
        for field_name in (
            "baseline_identifier",
            "process_version",
            "code_version",
        ):
            if getattr(value, field_name) != getattr(package, field_name):
                raise PaperTestEntryGovernanceError(
                    f"entry decision {field_name} does not match package"
                )
        if (
            value.state is PaperTestEntryDecisionState.APPROVED
            and package.state is not PaperTestEligibilityState.ELIGIBLE
        ):
            raise PaperTestEntryGovernanceError(
                "blocked eligibility package cannot be approved"
            )
        return self._append(
            identifier=value.identifier,
            baseline_identifier=value.baseline_identifier,
            event_type=PaperTestGovernanceEventType.ENTRY_DECISION,
            occurred_at=value.decided_at,
            payload=value.to_dict(),
        )

    def _values(
        self,
        baseline_identifier: str,
        event_type: PaperTestGovernanceEventType,
    ) -> tuple[dict[str, Any], ...]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE baseline_identifier=? AND event_type=? ORDER BY sequence",
                (baseline_identifier, event_type.value),
            ).fetchall()
        return tuple(json.loads(str(row[0])) for row in rows)

    def freezes(self, baseline_identifier: str) -> tuple[InvestmentProcessFreeze, ...]:
        return tuple(
            InvestmentProcessFreeze.from_dict(item)
            for item in self._values(
                baseline_identifier,
                PaperTestGovernanceEventType.PROCESS_FREEZE,
            )
        )

    def packages(
        self,
        baseline_identifier: str,
    ) -> tuple[ControlledPaperTestEligibilityPackage, ...]:
        return tuple(
            ControlledPaperTestEligibilityPackage.from_dict(item)
            for item in self._values(
                baseline_identifier,
                PaperTestGovernanceEventType.ELIGIBILITY_PACKAGE,
            )
        )

    def decisions(
        self,
        baseline_identifier: str,
    ) -> tuple[ControlledPaperTestEntryDecision, ...]:
        return tuple(
            ControlledPaperTestEntryDecision.from_dict(item)
            for item in self._values(
                baseline_identifier,
                PaperTestGovernanceEventType.ENTRY_DECISION,
            )
        )

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        for expected, row in enumerate(rows, start=1):
            if int(row[0]) != expected or str(row[6]) != previous:
                raise PaperTestEntryIntegrityError(
                    "paper-test entry governance chain is not contiguous"
                )
            actual = self._hash(
                int(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                str(row[6]),
            )
            if str(row[7]) != actual:
                raise PaperTestEntryIntegrityError(
                    "paper-test entry governance content hash is invalid"
                )
            previous = actual
        return True


__all__ = [
    "ControlledPaperTestEligibilityPackage",
    "ControlledPaperTestEntryDecision",
    "InvestmentProcessFreeze",
    "PaperTestEligibilityState",
    "PaperTestEntryDecisionState",
    "PaperTestEntryGovernanceError",
    "PaperTestEntryIntegrityError",
    "PaperTestEntryPackageAssembler",
    "PaperTestGovernanceEventType",
    "ProcessFreezeState",
    "SQLitePaperTestEntryGovernanceStore",
    "canonical_process_bundle_sha256",
]
