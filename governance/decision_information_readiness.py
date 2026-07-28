"""Fail-closed readiness authority for maximum decision-relevant information.

This scope complements market-operating data. It governs current events, news,
policy, transcripts, estimates, positioning, derivatives, physical activity,
weather, on-chain evidence, and alternative data without confusing availability
with reliability or investment authority.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class DecisionInformationReadinessError(RuntimeError):
    """Raised when the maximum-information manifest is invalid."""


class DecisionInformationReadinessState(str, Enum):
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class DecisionInformationDomain(str, Enum):
    CURRENT_EVENTS_NEWS = "current_events_news"
    GEOPOLITICAL_SECURITY = "geopolitical_security"
    GOVERNMENT_POLICY_REGULATION = "government_policy_regulation"
    CENTRAL_BANK_COMMUNICATIONS = "central_bank_communications"
    ELECTIONS_POLITICAL_RISK = "elections_political_risk"
    LEGAL_LITIGATION_SANCTIONS = "legal_litigation_sanctions"
    PUBLIC_HEALTH = "public_health"
    CYBERSECURITY_INCIDENTS = "cybersecurity_incidents"
    FILINGS_CORPORATE_DISCLOSURES = "filings_corporate_disclosures"
    EARNINGS_CALL_TRANSCRIPTS = "earnings_call_transcripts"
    MANAGEMENT_GUIDANCE = "management_guidance"
    ANALYST_ESTIMATES_REVISIONS = "analyst_estimates_revisions"
    CREDIT_RATINGS_DEFAULTS = "credit_ratings_defaults"
    OPTIONS_IMPLIED_EXPECTATIONS = "options_implied_expectations"
    FUTURES_POSITIONING = "futures_positioning"
    FUND_FLOWS_POSITIONING = "fund_flows_positioning"
    SHORT_INTEREST_SECURITIES_LENDING = "short_interest_securities_lending"
    INSIDER_INSTITUTIONAL_OWNERSHIP = "insider_institutional_ownership"
    COMMODITY_PHYSICAL_BALANCES = "commodity_physical_balances"
    SUPPLY_CHAIN_SHIPPING_INVENTORIES = "supply_chain_shipping_inventories"
    WEATHER_CLIMATE_DISASTERS = "weather_climate_disasters"
    ENERGY_GRID_POWER = "energy_grid_power"
    CONSUMER_ACTIVITY = "consumer_activity"
    LABOR_WEB_ACTIVITY = "labor_web_activity"
    REAL_ESTATE_ACTIVITY = "real_estate_activity"
    ONCHAIN_CRYPTO_NETWORK = "onchain_crypto_network"
    SOCIAL_SEARCH_SENTIMENT = "social_search_sentiment"
    PATENTS_TECHNOLOGY_INNOVATION = "patents_technology_innovation"


class DecisionInformationSourceRole(str, Enum):
    OFFICIAL = "official"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    VALIDATION = "validation"
    ALTERNATIVE = "alternative"


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


def _bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


@dataclass(frozen=True, slots=True)
class DecisionInformationSourceCapability:
    identifier: str
    source_name: str
    role: DecisionInformationSourceRole
    independence_group: str
    enabled: bool
    domains: tuple[DecisionInformationDomain, ...]
    authoritative_domains: tuple[DecisionInformationDomain, ...]
    credential_environment_variables: tuple[str, ...]
    usage_rights_approved: bool
    storage_and_backup_approved: bool
    derived_analytics_approved: bool
    internal_display_approved: bool
    paper_simulation_approved: bool
    event_time_supported: bool
    publication_time_supported: bool
    availability_time_supported: bool
    correction_history_supported: bool
    historical_coverage_supported: bool
    provenance_complete: bool
    entity_mapping_supported: bool
    geographic_mapping_supported: bool
    reliability_policy_defined: bool
    manipulation_controls_defined: bool
    deduplication_supported: bool
    service_level_defined: bool
    certification_required: bool
    certification_identifier: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "source_name", "independence_group"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.role, DecisionInformationSourceRole):
            raise TypeError("role must be DecisionInformationSourceRole")
        if not isinstance(self.domains, tuple) or not self.domains:
            raise ValueError("domains must contain at least one domain")
        if not all(isinstance(item, DecisionInformationDomain) for item in self.domains):
            raise TypeError("domains must contain DecisionInformationDomain values")
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("domains cannot contain duplicates")
        if not isinstance(self.authoritative_domains, tuple) or not all(
            isinstance(item, DecisionInformationDomain) for item in self.authoritative_domains
        ):
            raise TypeError("authoritative_domains must contain DecisionInformationDomain values")
        if set(self.authoritative_domains) - set(self.domains):
            raise ValueError("authoritative_domains must be included in domains")
        object.__setattr__(
            self,
            "credential_environment_variables",
            tuple(item.upper() for item in _texts(self.credential_environment_variables, field_name="credential_environment_variables")),
        )
        for field_name in (
            "enabled",
            "usage_rights_approved",
            "storage_and_backup_approved",
            "derived_analytics_approved",
            "internal_display_approved",
            "paper_simulation_approved",
            "event_time_supported",
            "publication_time_supported",
            "availability_time_supported",
            "correction_history_supported",
            "historical_coverage_supported",
            "provenance_complete",
            "entity_mapping_supported",
            "geographic_mapping_supported",
            "reliability_policy_defined",
            "manipulation_controls_defined",
            "deduplication_supported",
            "service_level_defined",
            "certification_required",
        ):
            _bool(getattr(self, field_name), field_name=field_name)
        if self.certification_identifier is not None:
            object.__setattr__(
                self,
                "certification_identifier",
                _text(self.certification_identifier, field_name="certification_identifier"),
            )
        object.__setattr__(self, "limitations", _texts(self.limitations, field_name="limitations"))

    def deficiencies(
        self,
        environment: Mapping[str, str],
        *,
        domain: DecisionInformationDomain,
        authoritative_required: bool,
    ) -> tuple[str, ...]:
        issues: list[str] = []
        if domain not in self.domains:
            issues.append(f"does not cover {domain.value}")
        if authoritative_required and domain not in self.authoritative_domains:
            issues.append(f"is not authoritative for {domain.value}")
        if not self.enabled:
            issues.append("source is not enabled")
        missing = tuple(
            name
            for name in self.credential_environment_variables
            if not str(environment.get(name, "")).strip()
        )
        if missing:
            issues.append("missing credentials/configuration: " + ", ".join(missing))
        checks = {
            "usage rights not approved": self.usage_rights_approved,
            "storage and backup rights not approved": self.storage_and_backup_approved,
            "derived analytics rights not approved": self.derived_analytics_approved,
            "internal display rights not approved": self.internal_display_approved,
            "paper-simulation use not approved": self.paper_simulation_approved,
            "event-time support not approved": self.event_time_supported,
            "publication-time support not approved": self.publication_time_supported,
            "availability-time support not approved": self.availability_time_supported,
            "correction history not supported": self.correction_history_supported,
            "historical coverage not approved": self.historical_coverage_supported,
            "provenance is incomplete": self.provenance_complete,
            "entity mapping is unavailable": self.entity_mapping_supported,
            "geographic mapping is unavailable": self.geographic_mapping_supported,
            "reliability policy is undefined": self.reliability_policy_defined,
            "manipulation controls are undefined": self.manipulation_controls_defined,
            "deduplication is unavailable": self.deduplication_supported,
            "service-level policy is undefined": self.service_level_defined,
        }
        issues.extend(label for label, passed in checks.items() if not passed)
        if self.certification_required and self.certification_identifier is None:
            issues.append("source certification is missing")
        return tuple(issues)


@dataclass(frozen=True, slots=True)
class DecisionInformationCoverageRequirement:
    domain: DecisionInformationDomain
    source_identifiers: tuple[str, ...]
    minimum_ready_sources: int
    minimum_independence_groups: int
    authoritative_required: bool
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.domain, DecisionInformationDomain):
            raise TypeError("domain must be DecisionInformationDomain")
        object.__setattr__(
            self,
            "source_identifiers",
            _texts(self.source_identifiers, field_name="source_identifiers", minimum=1),
        )
        for field_name in ("minimum_ready_sources", "minimum_independence_groups"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.minimum_ready_sources > len(self.source_identifiers):
            raise ValueError("minimum_ready_sources exceeds source count")
        if self.minimum_independence_groups > self.minimum_ready_sources:
            raise ValueError("minimum_independence_groups exceeds minimum_ready_sources")
        _bool(self.authoritative_required, field_name="authoritative_required")
        object.__setattr__(self, "rationale", _text(self.rationale, field_name="rationale"))


@dataclass(frozen=True, slots=True)
class MaximumDecisionInformationManifest:
    identifier: str
    schema_version: str
    objective: str
    require_complete_scope: bool
    sources: tuple[DecisionInformationSourceCapability, ...]
    requirements: tuple[DecisionInformationCoverageRequirement, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "schema_version", "objective"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        _bool(self.require_complete_scope, field_name="require_complete_scope")
        if not isinstance(self.sources, tuple) or not self.sources:
            raise ValueError("sources cannot be empty")
        if not all(isinstance(item, DecisionInformationSourceCapability) for item in self.sources):
            raise TypeError("sources must contain DecisionInformationSourceCapability values")
        source_ids = tuple(item.identifier for item in self.sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source identifiers cannot repeat")
        if not isinstance(self.requirements, tuple) or not self.requirements:
            raise ValueError("requirements cannot be empty")
        if not all(isinstance(item, DecisionInformationCoverageRequirement) for item in self.requirements):
            raise TypeError("requirements must contain DecisionInformationCoverageRequirement values")
        domains = tuple(item.domain for item in self.requirements)
        if len(domains) != len(set(domains)):
            raise ValueError("information domains cannot repeat")
        if self.require_complete_scope:
            missing = set(DecisionInformationDomain) - set(domains)
            if missing:
                raise ValueError(
                    "maximum decision-information scope is missing: "
                    + ", ".join(sorted(item.value for item in missing))
                )
        known = set(source_ids)
        for requirement in self.requirements:
            unknown = set(requirement.source_identifiers) - known
            if unknown:
                raise ValueError(
                    f"{requirement.domain.value} references unknown sources: {sorted(unknown)}"
                )

    @property
    def required_environment_variables(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    variable
                    for source in self.sources
                    for variable in source.credential_environment_variables
                }
            )
        )


@dataclass(frozen=True, slots=True)
class DecisionInformationDomainAssessment:
    domain: DecisionInformationDomain
    required_source_identifiers: tuple[str, ...]
    ready_source_identifiers: tuple[str, ...]
    ready_independence_groups: tuple[str, ...]
    minimum_ready_sources: int
    minimum_independence_groups: int
    authoritative_required: bool
    rationale: str
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return (
            len(self.ready_source_identifiers) >= self.minimum_ready_sources
            and len(self.ready_independence_groups) >= self.minimum_independence_groups
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "required_source_identifiers": list(self.required_source_identifiers),
            "ready_source_identifiers": list(self.ready_source_identifiers),
            "ready_independence_groups": list(self.ready_independence_groups),
            "minimum_ready_sources": self.minimum_ready_sources,
            "minimum_independence_groups": self.minimum_independence_groups,
            "authoritative_required": self.authoritative_required,
            "rationale": self.rationale,
            "ready": self.ready,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class MaximumDecisionInformationReadinessReport:
    manifest_identifier: str
    manifest_schema_version: str
    state: DecisionInformationReadinessState
    maximum_scope_declared: bool
    all_domains_ready: bool
    current_events_and_news_ready: bool
    structured_information_ready: bool
    unstructured_information_ready: bool
    alternative_information_ready: bool
    missing_environment_variables: tuple[str, ...]
    domains: tuple[DecisionInformationDomainAssessment, ...]
    blockers: tuple[str, ...]
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if self.real_money_authorized:
            raise ValueError("information readiness cannot authorize real money")

    @property
    def evidence_identifier(self) -> str:
        return f"maximum-decision-information-readiness:{self.manifest_identifier}:{self.state.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "maximum-decision-information-readiness-report.v1",
            "manifest_identifier": self.manifest_identifier,
            "manifest_schema_version": self.manifest_schema_version,
            "state": self.state.value,
            "maximum_scope_declared": self.maximum_scope_declared,
            "all_domains_ready": self.all_domains_ready,
            "current_events_and_news_ready": self.current_events_and_news_ready,
            "structured_information_ready": self.structured_information_ready,
            "unstructured_information_ready": self.unstructured_information_ready,
            "alternative_information_ready": self.alternative_information_ready,
            "missing_environment_variables": list(self.missing_environment_variables),
            "domains": [item.to_dict() for item in self.domains],
            "blockers": list(self.blockers),
            "evidence_identifier": self.evidence_identifier,
            "real_money_authorized": False,
        }


class MaximumDecisionInformationReadinessEvaluator:
    _UNSTRUCTURED = {
        DecisionInformationDomain.CURRENT_EVENTS_NEWS,
        DecisionInformationDomain.GEOPOLITICAL_SECURITY,
        DecisionInformationDomain.GOVERNMENT_POLICY_REGULATION,
        DecisionInformationDomain.CENTRAL_BANK_COMMUNICATIONS,
        DecisionInformationDomain.ELECTIONS_POLITICAL_RISK,
        DecisionInformationDomain.LEGAL_LITIGATION_SANCTIONS,
        DecisionInformationDomain.PUBLIC_HEALTH,
        DecisionInformationDomain.CYBERSECURITY_INCIDENTS,
        DecisionInformationDomain.FILINGS_CORPORATE_DISCLOSURES,
        DecisionInformationDomain.EARNINGS_CALL_TRANSCRIPTS,
        DecisionInformationDomain.MANAGEMENT_GUIDANCE,
        DecisionInformationDomain.PATENTS_TECHNOLOGY_INNOVATION,
    }
    _ALTERNATIVE = {
        DecisionInformationDomain.SUPPLY_CHAIN_SHIPPING_INVENTORIES,
        DecisionInformationDomain.WEATHER_CLIMATE_DISASTERS,
        DecisionInformationDomain.ENERGY_GRID_POWER,
        DecisionInformationDomain.CONSUMER_ACTIVITY,
        DecisionInformationDomain.LABOR_WEB_ACTIVITY,
        DecisionInformationDomain.REAL_ESTATE_ACTIVITY,
        DecisionInformationDomain.ONCHAIN_CRYPTO_NETWORK,
        DecisionInformationDomain.SOCIAL_SEARCH_SENTIMENT,
    }

    def evaluate(
        self,
        manifest: MaximumDecisionInformationManifest,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> MaximumDecisionInformationReadinessReport:
        if not isinstance(manifest, MaximumDecisionInformationManifest):
            raise TypeError("manifest must be MaximumDecisionInformationManifest")
        values = dict(os.environ if environment is None else environment)
        source_by_id = {item.identifier: item for item in manifest.sources}
        assessments: list[DecisionInformationDomainAssessment] = []
        missing_environment: set[str] = set()
        for requirement in manifest.requirements:
            ready: list[str] = []
            groups: list[str] = []
            blockers: list[str] = []
            for source_identifier in requirement.source_identifiers:
                source = source_by_id[source_identifier]
                deficiencies = source.deficiencies(
                    values,
                    domain=requirement.domain,
                    authoritative_required=requirement.authoritative_required,
                )
                if deficiencies:
                    blockers.extend(
                        f"{source.identifier}: {item}" for item in deficiencies
                    )
                    missing_environment.update(
                        variable
                        for variable in source.credential_environment_variables
                        if not str(values.get(variable, "")).strip()
                    )
                else:
                    ready.append(source.identifier)
                    groups.append(source.independence_group)
            distinct_groups = tuple(dict.fromkeys(groups))
            if len(ready) < requirement.minimum_ready_sources:
                blockers.append(
                    f"requires {requirement.minimum_ready_sources} ready source(s); found {len(ready)}"
                )
            if len(distinct_groups) < requirement.minimum_independence_groups:
                blockers.append(
                    f"requires {requirement.minimum_independence_groups} independent source group(s); found {len(distinct_groups)}"
                )
            assessments.append(
                DecisionInformationDomainAssessment(
                    domain=requirement.domain,
                    required_source_identifiers=requirement.source_identifiers,
                    ready_source_identifiers=tuple(ready),
                    ready_independence_groups=distinct_groups,
                    minimum_ready_sources=requirement.minimum_ready_sources,
                    minimum_independence_groups=requirement.minimum_independence_groups,
                    authoritative_required=requirement.authoritative_required,
                    rationale=requirement.rationale,
                    blockers=tuple(dict.fromkeys(blockers)),
                )
            )
        by_domain = {item.domain: item for item in assessments}
        maximum_declared = set(by_domain) == set(DecisionInformationDomain)
        all_ready = maximum_declared and all(item.ready for item in assessments)
        current_ready = by_domain[DecisionInformationDomain.CURRENT_EVENTS_NEWS].ready
        unstructured_ready = all(by_domain[item].ready for item in self._UNSTRUCTURED)
        alternative_ready = all(by_domain[item].ready for item in self._ALTERNATIVE)
        structured_ready = all(
            item.ready
            for item in assessments
            if item.domain not in self._UNSTRUCTURED | self._ALTERNATIVE
        )
        ready_count = sum(item.ready for item in assessments)
        state = (
            DecisionInformationReadinessState.READY
            if all_ready
            else DecisionInformationReadinessState.PARTIAL
            if ready_count
            else DecisionInformationReadinessState.BLOCKED
        )
        blockers = tuple(
            f"{assessment.domain.value}: {blocker}"
            for assessment in assessments
            for blocker in assessment.blockers
        )
        return MaximumDecisionInformationReadinessReport(
            manifest_identifier=manifest.identifier,
            manifest_schema_version=manifest.schema_version,
            state=state,
            maximum_scope_declared=maximum_declared,
            all_domains_ready=all_ready,
            current_events_and_news_ready=current_ready,
            structured_information_ready=structured_ready,
            unstructured_information_ready=unstructured_ready,
            alternative_information_ready=alternative_ready,
            missing_environment_variables=tuple(sorted(missing_environment)),
            domains=tuple(assessments),
            blockers=blockers,
        )


def _payload_bool(payload: Mapping[str, Any], key: str, *, default: bool | None = None) -> bool:
    if key not in payload:
        if default is None:
            raise KeyError(key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a bool")
    return value


def source_capability_from_payload(payload: Mapping[str, Any]) -> DecisionInformationSourceCapability:
    return DecisionInformationSourceCapability(
        identifier=str(payload["identifier"]),
        source_name=str(payload["source_name"]),
        role=DecisionInformationSourceRole(str(payload["role"])),
        independence_group=str(payload["independence_group"]),
        enabled=_payload_bool(payload, "enabled"),
        domains=tuple(DecisionInformationDomain(str(item)) for item in payload["domains"]),
        authoritative_domains=tuple(
            DecisionInformationDomain(str(item))
            for item in payload.get("authoritative_domains", ())
        ),
        credential_environment_variables=tuple(
            str(item) for item in payload.get("credential_environment_variables", ())
        ),
        usage_rights_approved=_payload_bool(payload, "usage_rights_approved"),
        storage_and_backup_approved=_payload_bool(payload, "storage_and_backup_approved"),
        derived_analytics_approved=_payload_bool(payload, "derived_analytics_approved"),
        internal_display_approved=_payload_bool(payload, "internal_display_approved"),
        paper_simulation_approved=_payload_bool(payload, "paper_simulation_approved"),
        event_time_supported=_payload_bool(payload, "event_time_supported"),
        publication_time_supported=_payload_bool(payload, "publication_time_supported"),
        availability_time_supported=_payload_bool(payload, "availability_time_supported"),
        correction_history_supported=_payload_bool(payload, "correction_history_supported"),
        historical_coverage_supported=_payload_bool(payload, "historical_coverage_supported"),
        provenance_complete=_payload_bool(payload, "provenance_complete"),
        entity_mapping_supported=_payload_bool(payload, "entity_mapping_supported"),
        geographic_mapping_supported=_payload_bool(payload, "geographic_mapping_supported"),
        reliability_policy_defined=_payload_bool(payload, "reliability_policy_defined"),
        manipulation_controls_defined=_payload_bool(payload, "manipulation_controls_defined"),
        deduplication_supported=_payload_bool(payload, "deduplication_supported"),
        service_level_defined=_payload_bool(payload, "service_level_defined"),
        certification_required=_payload_bool(payload, "certification_required"),
        certification_identifier=(
            None
            if payload.get("certification_identifier") is None
            else str(payload["certification_identifier"])
        ),
        limitations=tuple(str(item) for item in payload.get("limitations", ())),
    )


def manifest_from_payload(payload: Mapping[str, Any]) -> MaximumDecisionInformationManifest:
    if not isinstance(payload, Mapping):
        raise TypeError("maximum decision-information manifest must be an object")
    return MaximumDecisionInformationManifest(
        identifier=str(payload["identifier"]),
        schema_version=str(payload.get("schema_version", "maximum-decision-information-manifest.v1")),
        objective=str(payload["objective"]),
        require_complete_scope=_payload_bool(payload, "require_complete_scope", default=True),
        sources=tuple(source_capability_from_payload(item) for item in payload["sources"]),
        requirements=tuple(
            DecisionInformationCoverageRequirement(
                domain=DecisionInformationDomain(str(item["domain"])),
                source_identifiers=tuple(str(value) for value in item["source_identifiers"]),
                minimum_ready_sources=int(item.get("minimum_ready_sources", 1)),
                minimum_independence_groups=int(item.get("minimum_independence_groups", 1)),
                authoritative_required=_payload_bool(item, "authoritative_required", default=False),
                rationale=str(item["rationale"]),
            )
            for item in payload["requirements"]
        ),
    )


def load_maximum_decision_information_manifest(
    path: str | Path,
) -> MaximumDecisionInformationManifest:
    manifest_path = Path(path).expanduser()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DecisionInformationReadinessError(
            f"cannot read maximum decision-information manifest {str(manifest_path)!r}"
        ) from error
    try:
        return manifest_from_payload(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise DecisionInformationReadinessError(
            f"invalid maximum decision-information manifest {str(manifest_path)!r}: {error}"
        ) from error


__all__ = [
    "DecisionInformationCoverageRequirement",
    "DecisionInformationDomain",
    "DecisionInformationDomainAssessment",
    "DecisionInformationReadinessError",
    "DecisionInformationReadinessState",
    "DecisionInformationSourceCapability",
    "DecisionInformationSourceRole",
    "MaximumDecisionInformationManifest",
    "MaximumDecisionInformationReadinessEvaluator",
    "MaximumDecisionInformationReadinessReport",
    "load_maximum_decision_information_manifest",
    "manifest_from_payload",
    "source_capability_from_payload",
]
