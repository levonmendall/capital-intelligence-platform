"""Versioned registry of active SQLite authorities required for recovery.

The registry is the single production backup allow-list. Retired Investor Memory,
investment-policy, analytical-engine, regime-allocation, and weighted-committee
stores are intentionally excluded and explicitly prohibited from active backup
manifests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


RETIRED_BACKUP_AUTHORITIES = frozenset(
    {
        "analytical_engines",
        "investor_memory",
        "investment_policy",
        "regime_allocation",
        "weighted_committee",
    }
)


@dataclass(frozen=True, slots=True)
class CanonicalBackupAuthority:
    """One active SQLite authority and its recovery classification."""

    logical_name: str
    environment_variable: str
    default_filename: str
    category: str
    required_for_decision_reproduction: bool = True
    required_for_platform_recovery: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "logical_name",
            "environment_variable",
            "default_filename",
            "category",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if self.logical_name in RETIRED_BACKUP_AUTHORITIES:
            raise ValueError(
                f"retired authority cannot enter active backup registry: {self.logical_name}"
            )
        if not self.default_filename.endswith(".db"):
            raise ValueError("default_filename must be a SQLite .db file")
        if not isinstance(self.required_for_decision_reproduction, bool):
            raise TypeError("required_for_decision_reproduction must be a bool")
        if not isinstance(self.required_for_platform_recovery, bool):
            raise TypeError("required_for_platform_recovery must be a bool")

    def resolve(
        self,
        *,
        data_directory: Path,
        environ: Mapping[str, str],
    ) -> Path:
        configured = environ.get(self.environment_variable)
        return (
            Path(configured).expanduser()
            if configured and configured.strip()
            else data_directory / self.default_filename
        )

    def to_manifest_metadata(self, path: Path) -> dict[str, object]:
        return {
            "logical_name": self.logical_name,
            "category": self.category,
            "environment_variable": self.environment_variable,
            "configured_path": str(path),
            "required_for_decision_reproduction": (
                self.required_for_decision_reproduction
            ),
            "required_for_platform_recovery": (
                self.required_for_platform_recovery
            ),
        }


CANONICAL_BACKUP_AUTHORITIES: tuple[CanonicalBackupAuthority, ...] = (
    CanonicalBackupAuthority(
        "security_master",
        "CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATABASE",
        "security_master.db",
        "evidence",
    ),
    CanonicalBackupAuthority(
        "eligible_universe",
        "CAPITAL_INTELLIGENCE_ELIGIBLE_UNIVERSE_DATABASE",
        "eligible_universe.db",
        "evidence",
    ),
    CanonicalBackupAuthority(
        "full_universe_screening",
        "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE",
        "full_universe_screening.db",
        "evidence",
    ),
    CanonicalBackupAuthority(
        "production_context",
        "CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE",
        "production_context.db",
        "evidence",
    ),
    CanonicalBackupAuthority(
        "asset_specific_evidence",
        "CAPITAL_INTELLIGENCE_ASSET_SPECIFIC_EVIDENCE_DATABASE",
        "asset_specific_evidence.db",
        "evidence",
    ),
    CanonicalBackupAuthority(
        "institutional_journal",
        "CAPITAL_INTELLIGENCE_JOURNAL_DATABASE",
        "institutional_journal.db",
        "decision",
    ),
    CanonicalBackupAuthority(
        "canonical_portfolio",
        "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE",
        "canonical_portfolio.db",
        "portfolio",
    ),
    CanonicalBackupAuthority(
        "multi_asset_paper_execution",
        "CAPITAL_INTELLIGENCE_MULTI_ASSET_EXECUTION_DATABASE",
        "multi_asset_paper_execution.db",
        "execution",
    ),
    CanonicalBackupAuthority(
        "asset_class_governance",
        "CAPITAL_INTELLIGENCE_ASSET_CLASS_GOVERNANCE_DATABASE",
        "asset_class_governance.db",
        "governance",
    ),
    CanonicalBackupAuthority(
        "multi_asset_evaluation",
        "CAPITAL_INTELLIGENCE_MULTI_ASSET_EVALUATION_DATABASE",
        "multi_asset_evaluation.db",
        "evaluation",
    ),
    CanonicalBackupAuthority(
        "canonical_daily_operations",
        "CAPITAL_INTELLIGENCE_DAILY_OPERATION_DATABASE",
        "canonical_daily_operations.db",
        "operations",
    ),
    CanonicalBackupAuthority(
        "alerts",
        "CAPITAL_INTELLIGENCE_ALERT_DATABASE",
        "alerts.db",
        "operations",
    ),
    CanonicalBackupAuthority(
        "operational_slos",
        "CAPITAL_INTELLIGENCE_OPERATIONAL_SLO_DATABASE",
        "operational_slos.db",
        "operations",
    ),
    CanonicalBackupAuthority(
        "operational_incidents",
        "CAPITAL_INTELLIGENCE_OPERATIONAL_INCIDENT_DATABASE",
        "operational_incidents.db",
        "operations",
    ),
    CanonicalBackupAuthority(
        "resilience_exercises",
        "CAPITAL_INTELLIGENCE_RESILIENCE_DATABASE",
        "resilience_exercises.db",
        "operations",
    ),
    CanonicalBackupAuthority(
        "product_readiness_evidence",
        "CAPITAL_INTELLIGENCE_PRODUCT_READINESS_EVIDENCE_DATABASE",
        "product_readiness_evidence.db",
        "readiness",
    ),
    CanonicalBackupAuthority(
        "product_test_readiness",
        "CAPITAL_INTELLIGENCE_PRODUCT_TEST_READINESS_DATABASE",
        "product_test_readiness.db",
        "readiness",
    ),
    CanonicalBackupAuthority(
        "daily_intelligence_snapshots",
        "CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE",
        "daily_intelligence_snapshots.db",
        "read_model",
        required_for_decision_reproduction=False,
    ),
    CanonicalBackupAuthority(
        "identity",
        "CAPITAL_INTELLIGENCE_IDENTITY_DATABASE",
        "identity.db",
        "platform",
        required_for_decision_reproduction=False,
    ),
)


@dataclass(frozen=True, slots=True)
class CanonicalBackupRegistry:
    """Resolved, validated authority set for one deployment."""

    authorities: tuple[CanonicalBackupAuthority, ...]
    paths: tuple[tuple[str, Path], ...]
    schema_version: str = "canonical-backup-registry.v1"

    def __post_init__(self) -> None:
        if not self.authorities:
            raise ValueError("backup registry cannot be empty")
        logical_names = tuple(item.logical_name for item in self.authorities)
        if len(logical_names) != len(set(logical_names)):
            raise ValueError("backup registry contains duplicate logical names")
        if set(logical_names) & RETIRED_BACKUP_AUTHORITIES:
            raise ValueError("backup registry contains retired authorities")
        resolved_names = tuple(name for name, _ in self.paths)
        if resolved_names != logical_names:
            raise ValueError("resolved backup paths do not match authority order")
        normalized_paths = tuple(path.resolve(strict=False) for _, path in self.paths)
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ValueError("multiple active authorities resolve to the same path")
        if self.schema_version != "canonical-backup-registry.v1":
            raise ValueError("unsupported canonical backup registry schema")

    @property
    def sources(self) -> dict[str, Path]:
        return dict(self.paths)

    @property
    def required_logical_names(self) -> tuple[str, ...]:
        return tuple(
            item.logical_name
            for item in self.authorities
            if item.required_for_platform_recovery
        )

    @property
    def decision_reproduction_logical_names(self) -> tuple[str, ...]:
        return tuple(
            item.logical_name
            for item in self.authorities
            if item.required_for_decision_reproduction
        )

    @property
    def metadata(self) -> dict[str, dict[str, object]]:
        path_by_name = self.sources
        return {
            item.logical_name: item.to_manifest_metadata(
                path_by_name[item.logical_name]
            )
            for item in self.authorities
        }

    def validate_sources(self) -> tuple[str, ...]:
        missing = tuple(
            name
            for name, path in self.paths
            if name in self.required_logical_names and not path.is_file()
        )
        return missing

    def to_dict(self) -> dict[str, object]:
        missing = set(self.validate_sources())
        return {
            "schema_version": self.schema_version,
            "authority_count": len(self.authorities),
            "required_authority_count": len(self.required_logical_names),
            "decision_reproduction_authority_count": len(
                self.decision_reproduction_logical_names
            ),
            "missing_required_authorities": sorted(missing),
            "retired_authorities_present": [],
            "authorities": [
                {
                    **self.metadata[item.logical_name],
                    "available": item.logical_name not in missing,
                }
                for item in self.authorities
            ],
        }


def build_canonical_backup_registry(
    environ: Mapping[str, str] | None = None,
) -> CanonicalBackupRegistry:
    values = os.environ if environ is None else environ
    data_directory = Path(
        values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    paths = tuple(
        (
            authority.logical_name,
            authority.resolve(data_directory=data_directory, environ=values),
        )
        for authority in CANONICAL_BACKUP_AUTHORITIES
    )
    return CanonicalBackupRegistry(CANONICAL_BACKUP_AUTHORITIES, paths)


__all__ = [
    "CANONICAL_BACKUP_AUTHORITIES",
    "RETIRED_BACKUP_AUTHORITIES",
    "CanonicalBackupAuthority",
    "CanonicalBackupRegistry",
    "build_canonical_backup_registry",
]
