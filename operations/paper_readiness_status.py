"""Assemble the remaining paper-readiness objectives without inventing evidence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from governance.paper_execution_authority import (
    require_combined_paper_execution_authorization,
    require_human_paper_test_entry,
)
from governance.paper_test_entry import SQLitePaperTestEntryGovernanceStore
from governance.paper_trading_launch import (
    PaperTradingLaunchError,
    SQLitePaperTradingControlStore,
)
from governance.paper_trading_launch_authority import SQLitePaperTradingLaunchStore
from governance.provider_activation import SQLiteProviderActivationStore
from governance.stage_binding_approval import (
    SQLiteStageBindingApprovalStore,
    require_approved_stage_bindings,
)
from operations.execution_calibration import ExecutionCalibrationReport
from operations.paper_test_campaign import (
    PaperTestCampaignState,
    SQLitePaperTestCampaignStore,
)
from operations.provider_reconciliation import ProviderReconciliationReport


class PaperReadinessObjectiveState(str, Enum):
    COMPLETE = "complete"
    BLOCKED = "blocked"
    NOT_EVALUATED = "not_evaluated"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON evidence {source}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must encode an object: {source}")
    return value


@dataclass(frozen=True, slots=True)
class PaperReadinessObjective:
    name: str
    state: PaperReadinessObjectiveState
    blockers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, field_name="name"))
        if not isinstance(self.state, PaperReadinessObjectiveState):
            raise TypeError("state must be PaperReadinessObjectiveState")
        for field_name in ("blockers", "evidence_identifiers"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")
        if self.state is PaperReadinessObjectiveState.COMPLETE and self.blockers:
            raise ValueError("complete objective cannot contain blockers")
        if self.state is PaperReadinessObjectiveState.BLOCKED and not self.blockers:
            raise ValueError("blocked objective requires blockers")

    @property
    def complete(self) -> bool:
        return self.state is PaperReadinessObjectiveState.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "complete": self.complete,
            "blockers": list(self.blockers),
            "evidence_identifiers": list(self.evidence_identifiers),
        }


@dataclass(frozen=True, slots=True)
class PaperReadinessStatusReport:
    identifier: str
    evaluated_at: datetime
    baseline_identifier: str
    process_version: str
    code_version: str
    objectives: tuple[PaperReadinessObjective, ...]
    schema_version: str = "paper-readiness-objective-status.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.evaluated_at, field_name="evaluated_at")
        if not isinstance(self.objectives, tuple) or not all(
            isinstance(item, PaperReadinessObjective) for item in self.objectives
        ):
            raise TypeError("objectives must contain PaperReadinessObjective values")
        names = tuple(item.name for item in self.objectives)
        if len(names) != len(set(names)):
            raise ValueError("objective names cannot contain duplicates")
        if self.schema_version != "paper-readiness-objective-status.v1":
            raise ValueError("unsupported paper readiness status schema")

    @property
    def complete(self) -> bool:
        return all(item.complete for item in self.objectives)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "state": "complete" if self.complete else "blocked",
            "complete": self.complete,
            "objectives": [item.to_dict() for item in self.objectives],
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "secret_values_disclosed": False,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class PaperReadinessStatusInputs:
    provider_requirements: str | Path | None = None
    provider_activation_database: str | Path | None = None
    stage_bindings: str | Path | None = None
    stage_binding_database: str | Path | None = None
    reconciliation_reports: tuple[str | Path, ...] = ()
    execution_calibration_report: str | Path | None = None
    campaign_database: str | Path | None = None
    recovery_report: str | Path | None = None
    entry_database: str | Path | None = None
    launch_database: str | Path | None = None
    control_database: str | Path | None = None


class PaperReadinessStatusAssembler:
    """Evaluate objective completion from explicit persisted authorities."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self.environ = dict(os.environ if environ is None else environ)

    @staticmethod
    def _objective(
        name: str,
        blockers: Sequence[str],
        evidence: Sequence[str] = (),
        *,
        evaluated: bool = True,
    ) -> PaperReadinessObjective:
        normalized = tuple(dict.fromkeys(item for item in blockers if item))
        state = (
            PaperReadinessObjectiveState.NOT_EVALUATED
            if not evaluated
            else PaperReadinessObjectiveState.BLOCKED
            if normalized
            else PaperReadinessObjectiveState.COMPLETE
        )
        return PaperReadinessObjective(
            name=name,
            state=state,
            blockers=normalized,
            evidence_identifiers=tuple(dict.fromkeys(evidence)),
        )

    def _providers(
        self,
        path: str | Path | None,
        activation_database: str | Path | None,
        *,
        evaluated_at: datetime,
    ) -> tuple[PaperReadinessObjective, PaperReadinessObjective]:
        if path is None:
            missing = ("provider operational requirements were not supplied",)
            return (
                self._objective("licensed_and_certified_market_data_providers", missing),
                self._objective("reviewed_production_bindings_and_credentials", missing),
            )
        manifest = _load_object(path)
        providers = manifest.get("providers")
        if not isinstance(providers, list) or not providers:
            raise ValueError("provider requirements must contain providers")

        store = None
        store_error: str | None = None
        if activation_database is not None:
            try:
                store = SQLiteProviderActivationStore(activation_database)
                store.verify_integrity()
            except (OSError, TypeError, ValueError, RuntimeError) as error:
                store_error = str(error)

        licensing_blockers: list[str] = []
        credential_blockers: list[str] = []
        licensing_evidence: list[str] = []
        for item in providers:
            if not isinstance(item, Mapping):
                raise ValueError("provider requirement must encode an object")
            name = _text(item.get("name"), field_name="provider.name")
            if not bool(item.get("required", True)):
                continue
            provider_identifier = _text(
                item.get("provider_identifier"),
                field_name="provider.provider_identifier",
            )
            activation_required = bool(item.get("activation_required", True))
            if activation_required:
                if store_error is not None:
                    licensing_blockers.append(
                        f"{name}: provider activation registry is invalid: {store_error}"
                    )
                elif store is None:
                    licensing_blockers.append(
                        f"{name}: provider activation database is unavailable"
                    )
                else:
                    activation = store.active(
                        provider_identifier,
                        evaluated_at=evaluated_at,
                    )
                    if activation is None:
                        licensing_blockers.append(
                            f"{name}: active provider approval is unavailable"
                        )
                    elif not activation.enabled:
                        licensing_blockers.append(
                            f"{name}: latest provider approval is disabled"
                        )
                    else:
                        licensing_evidence.extend(
                            (
                                activation.identifier,
                                activation.certification_identifier,
                                *activation.source_identifiers,
                            )
                        )
            else:
                source_authority = item.get("source_authority_identifier")
                if source_authority is None:
                    licensing_blockers.append(
                        f"{name}: source-controlled approval identifier is unavailable"
                    )
                else:
                    licensing_evidence.append(
                        _text(
                            source_authority,
                            field_name="source_authority_identifier",
                        )
                    )

            for variable in item.get("credential_environments", ()):
                variable_name = _text(variable, field_name="credential_environment")
                if not self.environ.get(variable_name):
                    credential_blockers.append(
                        f"{name}: credential {variable_name} is unavailable"
                    )
            for variable in item.get("binding_environments", ()):
                variable_name = _text(variable, field_name="binding_environment")
                configured = self.environ.get(variable_name)
                if not configured:
                    credential_blockers.append(
                        f"{name}: binding {variable_name} is unavailable"
                    )
                elif not Path(configured).expanduser().is_file():
                    credential_blockers.append(
                        f"{name}: binding file for {variable_name} is unavailable"
                    )
        return (
            self._objective(
                "licensed_and_certified_market_data_providers",
                licensing_blockers,
                licensing_evidence,
            ),
            self._objective(
                "reviewed_production_bindings_and_credentials",
                credential_blockers,
            ),
        )

    def _stage_bindings(
        self,
        *,
        inputs: PaperReadinessStatusInputs,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        as_of: datetime,
    ) -> tuple[list[str], list[str]]:
        if inputs.stage_bindings is None or inputs.stage_binding_database is None:
            return ["reviewed stage bindings or approval database were not supplied"], []
        try:
            approval = require_approved_stage_bindings(
                inputs.stage_bindings,
                approval_database=inputs.stage_binding_database,
                baseline_identifier=baseline_identifier,
                process_version=process_version,
                code_version=code_version,
                evaluated_at=as_of,
                environ=self.environ,
            )
            SQLiteStageBindingApprovalStore(
                inputs.stage_binding_database
            ).verify_integrity()
            return [], [approval.identifier]
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            return [str(error)], []

    @staticmethod
    def _reconciliations(
        paths: tuple[str | Path, ...],
    ) -> PaperReadinessObjective:
        if not paths:
            return PaperReadinessStatusAssembler._objective(
                "completed_backfills_and_reconciliation",
                ("no provider reconciliation reports were supplied",),
            )
        blockers: list[str] = []
        evidence: list[str] = []
        for path in paths:
            try:
                report = ProviderReconciliationReport.from_dict(_load_object(path))
            except (KeyError, TypeError, ValueError) as error:
                blockers.append(f"{path}: {error}")
                continue
            evidence.append(report.identifier)
            if not report.passed:
                blockers.append(f"{report.identifier}: reconciliation is blocked")
        return PaperReadinessStatusAssembler._objective(
            "completed_backfills_and_reconciliation",
            blockers,
            evidence,
        )

    @staticmethod
    def _calibration(path: str | Path | None) -> PaperReadinessObjective:
        if path is None:
            return PaperReadinessStatusAssembler._objective(
                "execution_price_and_cost_calibration",
                ("execution calibration report was not supplied",),
            )
        try:
            report = ExecutionCalibrationReport.from_dict(_load_object(path))
        except (KeyError, TypeError, ValueError) as error:
            return PaperReadinessStatusAssembler._objective(
                "execution_price_and_cost_calibration",
                (str(error),),
            )
        blockers = () if report.passed else ("execution calibration is blocked",)
        return PaperReadinessStatusAssembler._objective(
            "execution_price_and_cost_calibration",
            blockers,
            (report.identifier,),
        )

    @staticmethod
    def _campaign(
        database: str | Path | None,
        baseline_identifier: str,
    ) -> PaperReadinessObjective:
        if database is None:
            return PaperReadinessStatusAssembler._objective(
                "five_day_live_burn_in_and_required_exercises",
                ("paper-test campaign database was not supplied",),
            )
        try:
            store = SQLitePaperTestCampaignStore(database)
            store.verify_integrity()
            reports = store.reports(baseline_identifier)
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            return PaperReadinessStatusAssembler._objective(
                "five_day_live_burn_in_and_required_exercises",
                (str(error),),
            )
        if not reports:
            return PaperReadinessStatusAssembler._objective(
                "five_day_live_burn_in_and_required_exercises",
                ("paper-test campaign report is unavailable",),
            )
        report = reports[-1]
        blockers = (
            ()
            if report.state is PaperTestCampaignState.SATISFIED
            else tuple(report.blockers) or (f"campaign state is {report.state.value}",)
        )
        return PaperReadinessStatusAssembler._objective(
            "five_day_live_burn_in_and_required_exercises",
            blockers,
            (report.identifier, *report.evidence_identifiers),
        )

    @staticmethod
    def _recovery(
        path: str | Path | None,
        *,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
    ) -> PaperReadinessObjective:
        if path is None:
            return PaperReadinessStatusAssembler._objective(
                "successful_encrypted_recovery_drill",
                ("recovery drill report was not supplied",),
            )
        try:
            value = _load_object(path)
            blockers = list(str(item) for item in value.get("blockers", ()))
            if value.get("status") != "passed":
                blockers.append(f"recovery status is {value.get('status', 'unavailable')}")
            for field_name, expected in (
                ("baseline_identifier", baseline_identifier),
                ("process_version", process_version),
                ("code_version", code_version),
            ):
                if value.get(field_name) != expected:
                    blockers.append(f"recovery {field_name} does not match")
            if int(value.get("production_mutation_count", 1)) != 0:
                blockers.append("recovery drill mutated production")
            identifier = _text(value.get("identifier"), field_name="recovery.identifier")
        except (TypeError, ValueError) as error:
            return PaperReadinessStatusAssembler._objective(
                "successful_encrypted_recovery_drill",
                (str(error),),
            )
        return PaperReadinessStatusAssembler._objective(
            "successful_encrypted_recovery_drill",
            blockers,
            (identifier,),
        )

    @staticmethod
    def _human_entry(
        database: str | Path | None,
        *,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        as_of: datetime,
    ) -> PaperReadinessObjective:
        if database is None:
            return PaperReadinessStatusAssembler._objective(
                "human_approval_of_exact_eligibility_package_and_cohort",
                ("paper-test entry governance database was not supplied",),
            )
        try:
            authorization = require_human_paper_test_entry(
                entry_store=SQLitePaperTestEntryGovernanceStore(database),
                baseline_identifier=baseline_identifier,
                process_version=process_version,
                code_version=code_version,
                as_of=as_of,
            )
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            return PaperReadinessStatusAssembler._objective(
                "human_approval_of_exact_eligibility_package_and_cohort",
                (str(error),),
            )
        return PaperReadinessStatusAssembler._objective(
            "human_approval_of_exact_eligibility_package_and_cohort",
            (),
            authorization.source_identifiers,
        )

    @staticmethod
    def _runtime(
        inputs: PaperReadinessStatusInputs,
        *,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        as_of: datetime,
    ) -> PaperReadinessObjective:
        if not all(
            (
                inputs.entry_database,
                inputs.launch_database,
                inputs.control_database,
            )
        ):
            return PaperReadinessStatusAssembler._objective(
                "activation_of_runtime_risk_switch",
                ("entry, launch, and runtime-control databases are required",),
            )
        try:
            authorization = require_combined_paper_execution_authorization(
                entry_store=SQLitePaperTestEntryGovernanceStore(inputs.entry_database),
                launch_store=SQLitePaperTradingLaunchStore(inputs.launch_database),
                control_store=SQLitePaperTradingControlStore(inputs.control_database),
                baseline_identifier=baseline_identifier,
                process_version=process_version,
                code_version=code_version,
                as_of=as_of,
            )
        except (
            PaperTradingLaunchError,
            OSError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as error:
            return PaperReadinessStatusAssembler._objective(
                "activation_of_runtime_risk_switch",
                (str(error),),
            )
        return PaperReadinessStatusAssembler._objective(
            "activation_of_runtime_risk_switch",
            (),
            authorization.source_identifiers,
        )

    def assemble(
        self,
        *,
        identifier: str,
        evaluated_at: datetime,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
        inputs: PaperReadinessStatusInputs,
    ) -> PaperReadinessStatusReport:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        baseline = _text(baseline_identifier, field_name="baseline_identifier")
        process = _text(process_version, field_name="process_version")
        code = _text(code_version, field_name="code_version")
        provider_objective, credential_objective = self._providers(
            inputs.provider_requirements,
            inputs.provider_activation_database,
            evaluated_at=timestamp,
        )
        stage_blockers, stage_evidence = self._stage_bindings(
            inputs=inputs,
            baseline_identifier=baseline,
            process_version=process,
            code_version=code,
            as_of=timestamp,
        )
        credential_objective = self._objective(
            credential_objective.name,
            (*credential_objective.blockers, *stage_blockers),
            (*credential_objective.evidence_identifiers, *stage_evidence),
        )
        objectives = (
            provider_objective,
            credential_objective,
            self._reconciliations(inputs.reconciliation_reports),
            self._calibration(inputs.execution_calibration_report),
            self._campaign(inputs.campaign_database, baseline),
            self._recovery(
                inputs.recovery_report,
                baseline_identifier=baseline,
                process_version=process,
                code_version=code,
            ),
            self._human_entry(
                inputs.entry_database,
                baseline_identifier=baseline,
                process_version=process,
                code_version=code,
                as_of=timestamp,
            ),
            self._runtime(
                inputs,
                baseline_identifier=baseline,
                process_version=process,
                code_version=code,
                as_of=timestamp,
            ),
        )
        return PaperReadinessStatusReport(
            identifier=identifier,
            evaluated_at=timestamp,
            baseline_identifier=baseline,
            process_version=process,
            code_version=code,
            objectives=objectives,
        )


__all__ = [
    "PaperReadinessObjective",
    "PaperReadinessObjectiveState",
    "PaperReadinessStatusAssembler",
    "PaperReadinessStatusInputs",
    "PaperReadinessStatusReport",
]
