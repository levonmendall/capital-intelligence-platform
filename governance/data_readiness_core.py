"""Fail-closed all-markets data-supply readiness governance.

The investment process may consider a market only when its required datasets are
mapped to usable providers.  This module intentionally separates four concerns:

* market scope -- paper eligible, decision relevant, evidence only, prohibited;
* dataset coverage -- the exact data domains required for each market;
* provider readiness -- credentials, usage rights, point-in-time behavior,
  provenance, service levels, and certification; and
* test authorization -- every non-prohibited market in the declared scope must
  be data ready before the global controlled-paper-test data gate can pass.

The manifest contains no secrets.  Credential names are resolved from the
runtime environment and reports disclose only missing variable names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
import json
import os

from cio.models import CandidateAssetClass


class DataReadinessError(RuntimeError):
    """Raised when a data-readiness manifest is invalid or incomplete."""


class MarketDataScopeState(str, Enum):
    """Permitted use of one market in the controlled test scope."""

    PAPER_ELIGIBLE = "paper_eligible"
    DECISION_RELEVANT = "decision_relevant"
    EVIDENCE_ONLY = "evidence_only"
    PROHIBITED = "prohibited"


class DataDomain(str, Enum):
    """Canonical datasets required by the all-markets investment process."""

    SECURITY_MASTER = "security_master"
    MARKET_PRICES = "market_prices"
    QUOTES_LIQUIDITY = "quotes_liquidity"
    CORPORATE_ACTIONS = "corporate_actions"
    FUNDAMENTALS = "fundamentals"
    FILINGS = "filings"
    MACRO = "macro"
    FX_RATES = "fx_rates"
    FIXED_INCOME_TERMS = "fixed_income_terms"
    CRYPTO_MARKET_STRUCTURE = "crypto_market_structure"
    COMMODITY_CURVES = "commodity_curves"
    DERIVATIVE_CONTRACTS = "derivative_contracts"
    MARGIN_COLLATERAL = "margin_collateral"
    VOLATILITY_SURFACES = "volatility_surfaces"
    MARKET_CALENDARS = "market_calendars"
    BENCHMARKS = "benchmarks"
    EXECUTION_INPUTS = "execution_inputs"


class DataProviderRole(str, Enum):
    """How a provider participates in the governed data supply chain."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    OFFICIAL = "official"
    VALIDATION = "validation"


class AllMarketsDataReadinessState(str, Enum):
    """Overall conclusion of one manifest evaluation."""

    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


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


def _bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


@dataclass(frozen=True, slots=True)
class ProviderDataCapability:
    """Audited readiness facts for one external or official data provider."""

    identifier: str
    provider_name: str
    role: DataProviderRole
    enabled: bool
    domains: tuple[DataDomain, ...]
    authoritative_domains: tuple[DataDomain, ...]
    credential_environment_variables: tuple[str, ...]
    usage_rights_approved: bool
    point_in_time_supported: bool
    historical_coverage_supported: bool
    provenance_complete: bool
    service_level_defined: bool
    storage_and_backup_approved: bool
    derived_analytics_approved: bool
    paper_simulation_approved: bool
    certification_required: bool
    certification_identifier: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "provider_name"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.role, DataProviderRole):
            raise TypeError("role must be DataProviderRole")
        for field_name in (
            "enabled",
            "usage_rights_approved",
            "point_in_time_supported",
            "historical_coverage_supported",
            "provenance_complete",
            "service_level_defined",
            "storage_and_backup_approved",
            "derived_analytics_approved",
            "paper_simulation_approved",
            "certification_required",
        ):
            _bool(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.domains, tuple) or not self.domains:
            raise ValueError("domains must contain at least one DataDomain")
        if not all(isinstance(item, DataDomain) for item in self.domains):
            raise TypeError("domains must contain DataDomain values")
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("domains cannot contain duplicates")
        if not isinstance(self.authoritative_domains, tuple):
            raise TypeError("authoritative_domains must be a tuple")
        if not all(
            isinstance(item, DataDomain) for item in self.authoritative_domains
        ):
            raise TypeError(
                "authoritative_domains must contain DataDomain values"
            )
        if len(self.authoritative_domains) != len(
            set(self.authoritative_domains)
        ):
            raise ValueError("authoritative_domains cannot contain duplicates")
        unsupported = set(self.authoritative_domains) - set(self.domains)
        if unsupported:
            raise ValueError(
                "authoritative_domains must be included in domains: "
                f"{sorted(item.value for item in unsupported)}"
            )
        object.__setattr__(
            self,
            "credential_environment_variables",
            _texts(
                self.credential_environment_variables,
                field_name="credential_environment_variables",
                uppercase=True,
            ),
        )
        if self.certification_identifier is not None:
            object.__setattr__(
                self,
                "certification_identifier",
                _text(
                    self.certification_identifier,
                    field_name="certification_identifier",
                ),
            )
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )

    def deficiencies(
        self,
        environment: Mapping[str, str],
        *,
        domain: DataDomain,
        paper_use: bool,
        authoritative_required: bool,
    ) -> tuple[str, ...]:
        """Return exact reasons this provider cannot satisfy one requirement."""

        issues: list[str] = []
        if domain not in self.domains:
            issues.append(f"does not cover {domain.value}")
        if authoritative_required and domain not in self.authoritative_domains:
            issues.append(f"is not authoritative for {domain.value}")
        if not self.enabled:
            issues.append("provider is not enabled")
        missing = tuple(
            variable
            for variable in self.credential_environment_variables
            if not str(environment.get(variable, "")).strip()
        )
        if missing:
            issues.append(
                "missing credentials/configuration: " + ", ".join(missing)
            )
        capability_checks = {
            "usage rights not approved": self.usage_rights_approved,
            "point-in-time support not approved": self.point_in_time_supported,
            "historical coverage not approved": (
                self.historical_coverage_supported
            ),
            "provenance is incomplete": self.provenance_complete,
            "service-level policy is undefined": self.service_level_defined,
            "storage and backup rights not approved": (
                self.storage_and_backup_approved
            ),
            "derived analytics rights not approved": (
                self.derived_analytics_approved
            ),
        }
        issues.extend(
            label for label, passed in capability_checks.items() if not passed
        )
        if paper_use and not self.paper_simulation_approved:
            issues.append("paper-simulation use not approved")
        if self.certification_required and self.certification_identifier is None:
            issues.append("provider certification is missing")
        return tuple(issues)


