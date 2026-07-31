"""Deployment, observability, backup, and operational hardening."""

from operations.backup import BackupError, BackupResult, SQLiteBackupManager
from operations.backup_registry import (
    CANONICAL_BACKUP_AUTHORITIES,
    RETIRED_BACKUP_AUTHORITIES,
    CanonicalBackupAuthority,
    CanonicalBackupRegistry,
    build_canonical_backup_registry,
)
from operations.config import OperationalSettings
from operations.daily_orchestration import (
    CANONICAL_DAILY_STAGE_ORDER,
    CallableStageRunner,
    CanonicalDailyOperationRequest,
    CanonicalDailyOperationResult,
    CanonicalDailyOperationsOrchestrator,
    CanonicalDailyStage,
    CanonicalDailyStageRequest,
    CanonicalDailyStageResult,
    CanonicalDailyStageRunner,
    CommandStageRunner,
    DailyOperationError,
    DailyOperationEventType,
    DailyOperationIntegrityError,
    DailyOperationStatus,
    FailureClassification,
    ReconciliationStatus,
    SQLiteCanonicalDailyOperationsStore,
    StageExecutionError,
    StageRetryPolicy,
    StageStatus,
    operation_result_to_dict,
)
from operations.daily_leases import (
    DailyOperationLeaseError,
    DailyOperationLeaseGrant,
    DailyOperationLeaseLost,
    FencedStageRunner,
    LeasedCanonicalDailyOperationsOrchestrator,
    LeasedSQLiteCanonicalDailyOperationsStore,
    StageFencingContext,
    assert_current_stage_fence,
    current_stage_fencing_context,
)
from operations.heartbeat import WorkerHeartbeat, WorkerHeartbeatStore
from operations.composite_readiness import (
    CompositeReadinessPolicy,
    CompositeReadinessReport,
    assess_composite_readiness,
    component_heartbeat_path,
)
from operations.incidents import (
    OperationalIncidentError,
    OperationalIncidentEvent,
    OperationalIncidentIntegrityError,
    OperationalIncidentSeverity,
    OperationalIncidentState,
    SQLiteOperationalIncidentStore,
)
from operations.logging import JsonFormatter, configure_logging, get_request_id, set_request_id
from operations.metrics import MetricRegistry
from operations.middleware import SlidingWindowRateLimiter, install_operational_middleware
from operations.paper_test_campaign import (
    REQUIRED_FAILURE_SCENARIOS,
    BurnInDayRecord,
    CampaignEventType,
    FailureScenarioKind,
    FailureScenarioRecord,
    FailureScenarioStatus,
    PaperTestCampaignBaseline,
    PaperTestCampaignError,
    PaperTestCampaignEvaluator,
    PaperTestCampaignIntegrityError,
    PaperTestCampaignReport,
    PaperTestCampaignState,
    SQLitePaperTestCampaignStore,
)
from operations.recovery_drill import (
    CanonicalRecoveryDrill,
    RecoveryDrillError,
    RecoveryDrillExpectation,
    RecoveryDrillIntegrityError,
    RecoveryDrillReport,
    RecoveryDrillStatus,
    RecoveryLineageProbe,
    SQLiteRecoveryDrillStore,
)
from operations.resilience import (
    ResilienceExerciseHarness,
    ResilienceExerciseIntegrityError,
    ResilienceExerciseKind,
    ResilienceExerciseOutcome,
    ResilienceExercisePolicy,
    ResilienceExerciseReport,
    ResilienceExerciseScenario,
    ResilienceExerciseStatus,
    SQLiteResilienceExerciseStore,
    policy_from_payload,
    scenario_from_payload,
)
from operations.slo import (
    DecisionEvaluationSLOObservation,
    FullUniverseCycleRecord,
    FullUniverseCycleStatus,
    OperationalSLOComponent,
    OperationalSLOEvaluator,
    OperationalSLOInputs,
    OperationalSLOIntegrityError,
    OperationalSLOName,
    OperationalSLOPolicy,
    OperationalSLOService,
    OperationalSLOSnapshot,
    OperationalSLOStatus,
    SQLiteOperationalSLOSource,
    SQLiteOperationalSLOStore,
    SecurityMasterSLOObservation,
    ThesisSLOObservation,
    build_operational_slo_service,
    operational_slo_policy_from_settings,
)

_LAZY_READINESS_EXPORTS = {
    "OperationalReadinessAssembler",
    "OperationalReadinessAssemblyPolicy",
    "OperationalReadinessAssemblyResult",
}
_LAZY_MARKET_READINESS_EXPORTS = {
    "CANONICAL_PIPELINE_DATASET_TYPES",
    "DATA_DOMAIN_DATASET_TYPE",
    "UniversalPaperMarketReadinessReport",
    "assess_universal_paper_market_readiness",
}
_LAZY_MARKET_REHEARSAL_EXPORTS = {
    "AllMarketsPaperRehearsalReport",
    "run_all_markets_paper_rehearsal",
}


def __getattr__(name: str):
    if name in _LAZY_READINESS_EXPORTS:
        from operations import readiness

        return getattr(readiness, name)
    if name in _LAZY_MARKET_READINESS_EXPORTS:
        from operations import paper_market_readiness

        return getattr(paper_market_readiness, name)
    if name in _LAZY_MARKET_REHEARSAL_EXPORTS:
        from operations import all_markets_paper_rehearsal

        return getattr(all_markets_paper_rehearsal, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BackupError",
    "BackupResult",
    "BurnInDayRecord",
    "CANONICAL_BACKUP_AUTHORITIES",
    "CANONICAL_DAILY_STAGE_ORDER",
    "CampaignEventType",
    "CallableStageRunner",
    "CanonicalBackupAuthority",
    "CanonicalBackupRegistry",
    "CanonicalDailyOperationRequest",
    "CanonicalDailyOperationResult",
    "CanonicalDailyOperationsOrchestrator",
    "CanonicalDailyStage",
    "CanonicalDailyStageRequest",
    "CanonicalDailyStageResult",
    "CanonicalDailyStageRunner",
    "CanonicalRecoveryDrill",
    "CommandStageRunner",
    "CompositeReadinessPolicy",
    "CompositeReadinessReport",
    "DailyOperationError",
    "DailyOperationEventType",
    "DailyOperationIntegrityError",
    "DailyOperationLeaseError",
    "DailyOperationLeaseGrant",
    "DailyOperationLeaseLost",
    "DailyOperationStatus",
    "DecisionEvaluationSLOObservation",
    "FailureClassification",
    "FailureScenarioKind",
    "FailureScenarioRecord",
    "FailureScenarioStatus",
    "FencedStageRunner",
    "FullUniverseCycleRecord",
    "FullUniverseCycleStatus",
    "JsonFormatter",
    "LeasedCanonicalDailyOperationsOrchestrator",
    "LeasedSQLiteCanonicalDailyOperationsStore",
    "MetricRegistry",
    "OperationalIncidentError",
    "OperationalIncidentEvent",
    "OperationalIncidentIntegrityError",
    "OperationalIncidentSeverity",
    "OperationalIncidentState",
    "OperationalReadinessAssembler",
    "OperationalReadinessAssemblyPolicy",
    "OperationalReadinessAssemblyResult",
    "OperationalSLOComponent",
    "OperationalSLOEvaluator",
    "OperationalSLOInputs",
    "OperationalSLOIntegrityError",
    "OperationalSLOName",
    "OperationalSLOPolicy",
    "OperationalSLOService",
    "OperationalSLOSnapshot",
    "OperationalSLOStatus",
    "OperationalSettings",
    "PaperTestCampaignBaseline",
    "PaperTestCampaignError",
    "PaperTestCampaignEvaluator",
    "PaperTestCampaignIntegrityError",
    "PaperTestCampaignReport",
    "PaperTestCampaignState",
    "REQUIRED_FAILURE_SCENARIOS",
    "RETIRED_BACKUP_AUTHORITIES",
    "ReconciliationStatus",
    "RecoveryDrillError",
    "RecoveryDrillExpectation",
    "RecoveryDrillIntegrityError",
    "RecoveryDrillReport",
    "RecoveryDrillStatus",
    "RecoveryLineageProbe",
    "ResilienceExerciseHarness",
    "ResilienceExerciseIntegrityError",
    "ResilienceExerciseKind",
    "ResilienceExerciseOutcome",
    "ResilienceExercisePolicy",
    "ResilienceExerciseReport",
    "ResilienceExerciseScenario",
    "ResilienceExerciseStatus",
    "SQLiteBackupManager",
    "SQLiteCanonicalDailyOperationsStore",
    "SQLiteOperationalIncidentStore",
    "SQLiteOperationalSLOSource",
    "SQLiteOperationalSLOStore",
    "SQLitePaperTestCampaignStore",
    "SQLiteRecoveryDrillStore",
    "SQLiteResilienceExerciseStore",
    "SecurityMasterSLOObservation",
    "SlidingWindowRateLimiter",
    "StageExecutionError",
    "StageFencingContext",
    "StageRetryPolicy",
    "StageStatus",
    "ThesisSLOObservation",
    "WorkerHeartbeat",
    "WorkerHeartbeatStore",
    "assess_composite_readiness",
    "component_heartbeat_path",
    "assert_current_stage_fence",
    "build_canonical_backup_registry",
    "build_operational_slo_service",
    "configure_logging",
    "current_stage_fencing_context",
    "get_request_id",
    "install_operational_middleware",
    "operation_result_to_dict",
    "operational_slo_policy_from_settings",
    "policy_from_payload",
    "scenario_from_payload",
    "set_request_id",
]
