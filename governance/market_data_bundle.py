"""Governed provider bundle required for broad all-market paper trading.

The all-markets data manifest deliberately describes *capability slots*.  This
module binds those slots to a concrete multi-provider operating stack without
placing credentials, contract terms, or legal approvals in source control.

A bundle can be internally valid while remaining externally blocked.  It only
becomes active when every required binding, credential reference, commercial
approval reference, certification identifier, and append-only provider
activation exists at the evaluation timestamp.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from data.provider_dataset import ProviderDatasetType
from governance.provider_activation import SQLiteProviderActivationStore
from providers.configured_dataset import ConfiguredDatasetProviderSettings


class MarketDataBundleError(RuntimeError):
    """Raised when a provider bundle or deployment evidence is invalid."""


class ProviderBundleRole(str, Enum):
    GLOBAL_EXECUTION_MARKET_DATA = "global_execution_market_data"
    GLOBAL_REFERENCE_CORPORATE_ACTIONS = "global_reference_corporate_actions"
    GLOBAL_FUNDAMENTALS = "global_fundamentals"
    EVALUATED_FIXED_INCOME = "evaluated_fixed_income"
    BROAD_HISTORICAL_MULTI_ASSET = "broad_historical_multi_asset"
    CRYPTO_VENUE_VALIDATION = "crypto_venue_validation"
    DERIVATIVE_CONTRACT_DATA = "derivative_contract_data"
    DERIVATIVE_MARGIN_DATA = "derivative_margin_data"
    VOLATILITY_SURFACE_DATA = "volatility_surface_data"


class ProviderBindingKind(str, Enum):
    CONFIGURED_DATASET = "configured_dataset"
    EODHD = "eodhd"
    CRYPTO_VENUES = "crypto_venues"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized




def _boolean(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value

def _configured(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    placeholders = (
        "replace-with",
        "inject-from",
        "pending",
        "placeholder",
        "todo",
        "example.com",
        "your-",
    )
    return not any(item in normalized for item in placeholders)


def _load_json(path: str | Path) -> Mapping[str, Any]:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MarketDataBundleError(
            f"cannot load provider binding {str(source)!r}"
        ) from error
    if not isinstance(payload, Mapping):
        raise MarketDataBundleError(
            f"provider binding {str(source)!r} must contain an object"
        )
    return payload


@dataclass(frozen=True, slots=True)
class ProviderBundleMember:
    identifier: str
    provider_identifier: str
    provider_name: str
    roles: tuple[ProviderBundleRole, ...]
    binding_kind: ProviderBindingKind
    credential_environment_variables: tuple[str, ...]
    binding_environment_variables: tuple[str, ...]
    contract_reference_environment_variables: tuple[str, ...]
    license_approval_environment_variables: tuple[str, ...]
    certification_environment_variables: tuple[str, ...]
    required_dataset_types: tuple[ProviderDatasetType, ...]
    required: bool = True
    activation_required: bool = True
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "provider_identifier", "provider_name"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.roles, tuple) or not self.roles:
            raise ValueError("roles must contain at least one role")
        if not all(isinstance(item, ProviderBundleRole) for item in self.roles):
            raise TypeError("roles must contain ProviderBundleRole values")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("roles cannot contain duplicates")
        if not isinstance(self.binding_kind, ProviderBindingKind):
            raise TypeError("binding_kind must be ProviderBindingKind")
        for field_name in (
            "credential_environment_variables",
            "binding_environment_variables",
            "contract_reference_environment_variables",
            "license_approval_environment_variables",
            "certification_environment_variables",
            "limitations",
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.required_dataset_types, tuple):
            raise TypeError("required_dataset_types must be a tuple")
        if not all(
            isinstance(item, ProviderDatasetType)
            for item in self.required_dataset_types
        ):
            raise TypeError(
                "required_dataset_types must contain ProviderDatasetType values"
            )
        if len(self.required_dataset_types) != len(
            set(self.required_dataset_types)
        ):
            raise ValueError("required_dataset_types cannot contain duplicates")
        for field_name in ("required", "activation_required"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderBundleMember":
        return cls(
            identifier=str(payload["identifier"]),
            provider_identifier=str(payload["provider_identifier"]),
            provider_name=str(payload["provider_name"]),
            roles=tuple(
                ProviderBundleRole(str(item)) for item in payload["roles"]
            ),
            binding_kind=ProviderBindingKind(str(payload["binding_kind"])),
            credential_environment_variables=tuple(
                str(item)
                for item in payload.get("credential_environment_variables", ())
            ),
            binding_environment_variables=tuple(
                str(item)
                for item in payload.get("binding_environment_variables", ())
            ),
            contract_reference_environment_variables=tuple(
                str(item)
                for item in payload.get(
                    "contract_reference_environment_variables", ()
                )
            ),
            license_approval_environment_variables=tuple(
                str(item)
                for item in payload.get(
                    "license_approval_environment_variables", ()
                )
            ),
            certification_environment_variables=tuple(
                str(item)
                for item in payload.get("certification_environment_variables", ())
            ),
            required_dataset_types=tuple(
                ProviderDatasetType(str(item))
                for item in payload.get("required_dataset_types", ())
            ),
            required=_boolean(payload.get("required", True), field_name="required"),
            activation_required=_boolean(
                payload.get("activation_required", True),
                field_name="activation_required",
            ),
            limitations=tuple(
                str(item) for item in payload.get("limitations", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class ProviderBundleRoleRequirement:
    role: ProviderBundleRole
    minimum_ready_members: int

    def __post_init__(self) -> None:
        if not isinstance(self.role, ProviderBundleRole):
            raise TypeError("role must be ProviderBundleRole")
        if isinstance(self.minimum_ready_members, bool) or not isinstance(
            self.minimum_ready_members, int
        ):
            raise TypeError("minimum_ready_members must be an integer")
        if self.minimum_ready_members < 1:
            raise ValueError("minimum_ready_members must be at least 1")

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ProviderBundleRoleRequirement":
        return cls(
            role=ProviderBundleRole(str(payload["role"])),
            minimum_ready_members=int(payload.get("minimum_ready_members", 1)),
        )


@dataclass(frozen=True, slots=True)
class AllMarketProviderBundle:
    identifier: str
    members: tuple[ProviderBundleMember, ...]
    role_requirements: tuple[ProviderBundleRoleRequirement, ...]
    schema_version: str = "all-market-provider-bundle.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identifier", _text(self.identifier, field_name="identifier")
        )
        if self.schema_version != "all-market-provider-bundle.v1":
            raise ValueError("unsupported all-market provider bundle schema")
        if not isinstance(self.members, tuple) or not self.members:
            raise ValueError("members must contain at least one provider")
        if not all(isinstance(item, ProviderBundleMember) for item in self.members):
            raise TypeError("members must contain ProviderBundleMember values")
        member_ids = tuple(item.identifier for item in self.members)
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("provider bundle member identifiers must be unique")
        provider_ids = tuple(item.provider_identifier for item in self.members)
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError(
                "provider bundle provider identifiers must be unique so activations remain auditable"
            )
        if not isinstance(self.role_requirements, tuple) or not self.role_requirements:
            raise ValueError("role_requirements must not be empty")
        if not all(
            isinstance(item, ProviderBundleRoleRequirement)
            for item in self.role_requirements
        ):
            raise TypeError(
                "role_requirements must contain ProviderBundleRoleRequirement values"
            )
        roles = tuple(item.role for item in self.role_requirements)
        if len(roles) != len(set(roles)):
            raise ValueError("role_requirements cannot duplicate a role")
        available = {
            role
            for member in self.members
            for role in member.roles
        }
        missing = set(roles) - available
        if missing:
            raise ValueError(
                "role requirements have no provider members: "
                + ", ".join(sorted(item.value for item in missing))
            )
        for requirement in self.role_requirements:
            candidates = sum(
                requirement.role in member.roles for member in self.members
            )
            if candidates < requirement.minimum_ready_members:
                raise ValueError(
                    f"role {requirement.role.value} requires "
                    f"{requirement.minimum_ready_members} members but only "
                    f"{candidates} are declared"
                )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AllMarketProviderBundle":
        if not isinstance(payload, Mapping):
            raise TypeError("provider bundle must be an object")
        raw_members = payload.get("members")
        raw_requirements = payload.get("role_requirements")
        if not isinstance(raw_members, list):
            raise TypeError("members must be an array")
        if not isinstance(raw_requirements, list):
            raise TypeError("role_requirements must be an array")
        if not all(isinstance(item, Mapping) for item in raw_members):
            raise TypeError("every member must be an object")
        if not all(isinstance(item, Mapping) for item in raw_requirements):
            raise TypeError("every role requirement must be an object")
        return cls(
            identifier=str(payload["identifier"]),
            members=tuple(
                ProviderBundleMember.from_dict(item) for item in raw_members
            ),
            role_requirements=tuple(
                ProviderBundleRoleRequirement.from_dict(item)
                for item in raw_requirements
            ),
            schema_version=str(
                payload.get(
                    "schema_version", "all-market-provider-bundle.v1"
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ProviderBundleMemberAssessment:
    identifier: str
    provider_identifier: str
    binding_ready: bool
    credentials_ready: bool
    commercial_evidence_ready: bool
    activation_active: bool
    ready: bool
    configured_dataset_types: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "provider_identifier": self.provider_identifier,
            "binding_ready": self.binding_ready,
            "credentials_ready": self.credentials_ready,
            "commercial_evidence_ready": self.commercial_evidence_ready,
            "activation_active": self.activation_active,
            "ready": self.ready,
            "configured_dataset_types": list(self.configured_dataset_types),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class ProviderBundleAssessment:
    bundle_identifier: str
    evaluated_at: datetime
    implementation_ready: bool
    external_inputs_ready: bool
    active: bool
    member_assessments: tuple[ProviderBundleMemberAssessment, ...]
    role_ready_counts: Mapping[str, int]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "all-market-provider-bundle-assessment.v1",
            "bundle_identifier": self.bundle_identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "implementation_ready": self.implementation_ready,
            "external_inputs_ready": self.external_inputs_ready,
            "active": self.active,
            "role_ready_counts": dict(self.role_ready_counts),
            "member_assessments": [
                item.to_dict() for item in self.member_assessments
            ],
            "blockers": list(self.blockers),
            "real_money_authorized": False,
        }


def load_all_market_provider_bundle(
    path: str | Path,
) -> AllMarketProviderBundle:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MarketDataBundleError(
            f"cannot load provider bundle {str(source)!r}"
        ) from error
    try:
        return AllMarketProviderBundle.from_dict(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise MarketDataBundleError(
            f"invalid provider bundle {str(source)!r}: {error}"
        ) from error


def _binding_paths(
    member: ProviderBundleMember,
    environment: Mapping[str, str],
) -> tuple[Path, ...]:
    values: list[Path] = []
    for name in member.binding_environment_variables:
        raw = str(environment.get(name, "")).strip()
        if not _configured(raw):
            continue
        for item in raw.replace(os.pathsep, ",").split(","):
            item = item.strip()
            if item:
                values.append(Path(item).expanduser())
    return tuple(values)


def _validate_binding(
    member: ProviderBundleMember,
    path: Path,
) -> tuple[set[ProviderDatasetType], tuple[str, ...]]:
    payload = _load_json(path)
    blockers: list[str] = []
    dataset_types: set[ProviderDatasetType] = set()
    if member.binding_kind is ProviderBindingKind.CONFIGURED_DATASET:
        try:
            settings = ConfiguredDatasetProviderSettings.from_dict(payload)
        except (KeyError, TypeError, ValueError) as error:
            return set(), (f"{path}: invalid configured dataset binding: {error}",)
        if settings.provider_identifier != member.provider_identifier:
            blockers.append(
                f"{path}: provider identifier {settings.provider_identifier!r} "
                f"does not match {member.provider_identifier!r}"
            )
        if not _configured(settings.base_url):
            blockers.append(f"{path}: provider base_url is still a placeholder")
        dataset_types.update(item.dataset_type for item in settings.bindings)
    elif member.binding_kind is ProviderBindingKind.EODHD:
        try:
            from providers.eodhd import load_eodhd_bindings

            registry = load_eodhd_bindings(path)
            if not registry.bindings:
                blockers.append(f"{path}: EODHD bindings must not be empty")
        except Exception as error:
            blockers.append(f"{path}: invalid EODHD binding: {error}")
        dataset_types.update(member.required_dataset_types)
    elif member.binding_kind is ProviderBindingKind.CRYPTO_VENUES:
        try:
            from providers.crypto_venues import load_crypto_venue_bindings

            registry = load_crypto_venue_bindings(path)
            if len(registry.bindings) < 2:
                blockers.append(
                    f"{path}: crypto venue bindings require at least two instruments"
                )
        except Exception as error:
            blockers.append(f"{path}: invalid crypto venue binding: {error}")
        dataset_types.update(member.required_dataset_types)
    return dataset_types, tuple(blockers)


def assess_all_market_provider_bundle(
    bundle: AllMarketProviderBundle,
    *,
    evaluated_at: datetime,
    environment: Mapping[str, str],
    provider_activation_store: SQLiteProviderActivationStore,
) -> ProviderBundleAssessment:
    if not isinstance(bundle, AllMarketProviderBundle):
        raise TypeError("bundle must be AllMarketProviderBundle")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    provider_activation_store.verify_integrity()
    assessments: list[ProviderBundleMemberAssessment] = []
    global_blockers: list[str] = []

    for member in bundle.members:
        blockers: list[str] = []
        missing_credentials = tuple(
            name
            for name in member.credential_environment_variables
            if not _configured(environment.get(name, ""))
        )
        credentials_ready = not missing_credentials
        if missing_credentials:
            blockers.append(
                "missing credentials/configuration: "
                + ", ".join(missing_credentials)
            )

        evidence_names = (
            member.contract_reference_environment_variables
            + member.license_approval_environment_variables
            + member.certification_environment_variables
        )
        missing_evidence = tuple(
            name
            for name in evidence_names
            if not _configured(environment.get(name, ""))
        )
        commercial_evidence_ready = not missing_evidence
        if missing_evidence:
            blockers.append(
                "missing contract/license/certification evidence: "
                + ", ".join(missing_evidence)
            )

        paths = _binding_paths(member, environment)
        binding_types: set[ProviderDatasetType] = set()
        binding_blockers: list[str] = []
        if member.binding_environment_variables and not paths:
            binding_blockers.append(
                "missing runtime binding: "
                + ", ".join(member.binding_environment_variables)
            )
        for path in paths:
            if not path.exists():
                binding_blockers.append(f"runtime binding does not exist: {path}")
                continue
            types, path_blockers = _validate_binding(member, path)
            binding_types.update(types)
            binding_blockers.extend(path_blockers)
        missing_types = set(member.required_dataset_types) - binding_types
        if missing_types:
            binding_blockers.append(
                "runtime bindings lack datasets: "
                + ", ".join(sorted(item.value for item in missing_types))
            )
        blockers.extend(binding_blockers)
        binding_ready = not member.binding_environment_variables or (
            bool(paths) and not binding_blockers
        )

        activation = provider_activation_store.active(
            member.provider_identifier,
            evaluated_at=evaluated_at,
        )
        activation_active = (
            not member.activation_required
            or (activation is not None and activation.enabled)
        )
        if not activation_active:
            blockers.append(
                f"no active provider activation for {member.provider_identifier}"
            )

        ready = (
            binding_ready
            and credentials_ready
            and commercial_evidence_ready
            and activation_active
        )
        assessments.append(
            ProviderBundleMemberAssessment(
                identifier=member.identifier,
                provider_identifier=member.provider_identifier,
                binding_ready=binding_ready,
                credentials_ready=credentials_ready,
                commercial_evidence_ready=commercial_evidence_ready,
                activation_active=activation_active,
                ready=ready,
                configured_dataset_types=tuple(
                    sorted(item.value for item in binding_types)
                ),
                blockers=tuple(dict.fromkeys(blockers)),
            )
        )

    by_identifier = {item.identifier: item for item in assessments}
    role_counts: dict[str, int] = {}
    for requirement in bundle.role_requirements:
        count = sum(
            by_identifier[member.identifier].ready
            for member in bundle.members
            if requirement.role in member.roles
        )
        role_counts[requirement.role.value] = count
        if count < requirement.minimum_ready_members:
            global_blockers.append(
                f"role {requirement.role.value} has {count} ready member(s); "
                f"requires {requirement.minimum_ready_members}"
            )

    required_assessments = tuple(
        by_identifier[member.identifier]
        for member in bundle.members
        if member.required
    )
    external_inputs_ready = all(
        item.binding_ready
        and item.credentials_ready
        and item.commercial_evidence_ready
        for item in required_assessments
    )
    active = external_inputs_ready and all(
        item.activation_active for item in required_assessments
    ) and not global_blockers
    return ProviderBundleAssessment(
        bundle_identifier=bundle.identifier,
        evaluated_at=evaluated_at,
        implementation_ready=True,
        external_inputs_ready=external_inputs_ready,
        active=active,
        member_assessments=tuple(assessments),
        role_ready_counts=role_counts,
        blockers=tuple(dict.fromkeys(global_blockers)),
    )


__all__ = [
    "AllMarketProviderBundle",
    "MarketDataBundleError",
    "ProviderBindingKind",
    "ProviderBundleAssessment",
    "ProviderBundleMember",
    "ProviderBundleMemberAssessment",
    "ProviderBundleRole",
    "ProviderBundleRoleRequirement",
    "assess_all_market_provider_bundle",
    "load_all_market_provider_bundle",
]
