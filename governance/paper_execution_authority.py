"""Combined authority required before any governed paper execution.

Three independent conclusions are required and none may substitute for another:

* the latest human-controlled paper-test entry decision must approve the latest
  exact eligibility package for the named cohort;
* the latest sustained operational launch assessment must remain ready; and
* the runtime risk switch must remain active and reference that launch report.

Every authority is exact-baseline, exact-process, exact-code, append-only, and
paper-only. No conclusion in this module authorizes real money or brokerage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from governance.paper_test_entry import (
    ControlledPaperTestEligibilityPackage,
    ControlledPaperTestEntryDecision,
    PaperTestEligibilityState,
    PaperTestEntryDecisionState,
    SQLitePaperTestEntryGovernanceStore,
)
from governance.paper_trading_launch import (
    PaperTradingControlState,
    PaperTradingLaunchError,
    PaperTradingLaunchReport,
    SQLitePaperTradingControlStore,
)
from governance.paper_trading_launch_authority import (
    SQLitePaperTradingLaunchStore,
)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class CombinedPaperExecutionAuthorization:
    """Exact paper-only authorization lineage for one execution boundary."""

    entry_package: ControlledPaperTestEligibilityPackage
    entry_decision: ControlledPaperTestEntryDecision
    launch_report: PaperTradingLaunchReport
    control_event_identifier: str

    @property
    def cohort_identifier(self) -> str:
        return self.entry_decision.cohort_identifier

    @property
    def source_identifiers(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.entry_package.identifier,
                    self.entry_package.fingerprint,
                    self.entry_decision.identifier,
                    self.launch_report.identifier,
                    self.launch_report.evidence_identifier,
                    self.control_event_identifier,
                    *self.entry_package.evidence_identifiers,
                    *self.launch_report.evidence_identifiers,
                )
            )
        )


def require_combined_paper_execution_authorization(
    *,
    entry_store: SQLitePaperTestEntryGovernanceStore,
    launch_store: SQLitePaperTradingLaunchStore,
    control_store: SQLitePaperTradingControlStore,
    baseline_identifier: str,
    process_version: str,
    code_version: str,
    as_of: datetime,
) -> CombinedPaperExecutionAuthorization:
    """Return the exact active paper authorization or fail closed.

    The latest package and latest decision govern. A later blocked package,
    suspension, revocation, expired decision, blocked launch, expired launch, or
    runtime halt prevents execution immediately.
    """

    baseline = _text(baseline_identifier, field_name="baseline_identifier")
    process = _text(process_version, field_name="process_version")
    code = _text(code_version, field_name="code_version")
    timestamp = _aware(as_of, field_name="as_of")

    entry_store.verify_integrity()
    packages = entry_store.packages(baseline)
    decisions = entry_store.decisions(baseline)
    if not packages:
        raise PaperTradingLaunchError(
            "controlled paper-test eligibility package is unavailable"
        )
    if not decisions:
        raise PaperTradingLaunchError(
            "human controlled paper-test entry decision is unavailable"
        )
    package = packages[-1]
    decision = decisions[-1]

    if package.state is not PaperTestEligibilityState.ELIGIBLE:
        raise PaperTradingLaunchError(
            "latest controlled paper-test eligibility package is blocked"
        )
    if decision.state is not PaperTestEntryDecisionState.APPROVED:
        raise PaperTradingLaunchError(
            "latest human controlled paper-test entry decision is not approved"
        )
    if not decision.active_at(timestamp):
        raise PaperTradingLaunchError(
            "human controlled paper-test entry decision is inactive or expired"
        )
    for field_name, expected in (
        ("baseline_identifier", baseline),
        ("process_version", process),
        ("code_version", code),
    ):
        if getattr(package, field_name) != expected:
            raise PaperTradingLaunchError(
                f"eligibility package {field_name} does not match execution"
            )
        if getattr(decision, field_name) != expected:
            raise PaperTradingLaunchError(
                f"entry decision {field_name} does not match execution"
            )
    if decision.package_identifier != package.identifier:
        raise PaperTradingLaunchError(
            "entry decision does not reference the latest eligibility package"
        )
    if decision.package_fingerprint != package.fingerprint:
        raise PaperTradingLaunchError(
            "entry decision eligibility fingerprint does not match"
        )

    launch = launch_store.latest_ready(
        baseline_identifier=baseline,
        process_version=process,
        code_version=code,
        as_of=timestamp,
    )
    if launch is None:
        raise PaperTradingLaunchError(
            "current sustained paper-launch certification is unavailable"
        )

    control_store.verify_integrity()
    control = control_store.active_event(
        baseline_identifier=baseline,
        process_version=process,
        code_version=code,
        as_of=timestamp,
    )
    if control is None or control.state is not PaperTradingControlState.ACTIVE:
        raise PaperTradingLaunchError("paper execution runtime switch is halted")
    if control.launch_report_identifier != launch.identifier:
        raise PaperTradingLaunchError(
            "runtime switch does not reference the current launch report"
        )

    return CombinedPaperExecutionAuthorization(
        entry_package=package,
        entry_decision=decision,
        launch_report=launch,
        control_event_identifier=control.identifier,
    )


__all__ = [
    "CombinedPaperExecutionAuthorization",
    "require_combined_paper_execution_authorization",
]
