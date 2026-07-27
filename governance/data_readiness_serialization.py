"""All-markets data-readiness manifest serialization."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping
from cio.models import CandidateAssetClass
from governance.data_readiness_models import (
    AllMarketsDataManifest, DataDomain, DataProviderRole, DataReadinessError,
    DatasetCoverageRequirement, MarketDataScope, MarketDataScopeState, ProviderDataCapability,
)

def _payload_bool(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: bool | None = None,
) -> bool:
    if key not in payload:
        if default is None:
            raise KeyError(key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a bool")
    return value


def provider_capability_from_payload(
    payload: Mapping[str, Any],
) -> ProviderDataCapability:
    return ProviderDataCapability(
        identifier=str(payload["identifier"]),
        provider_name=str(payload["provider_name"]),
        role=DataProviderRole(str(payload["role"])),
        enabled=_payload_bool(payload, "enabled"),
        domains=tuple(DataDomain(str(item)) for item in payload["domains"]),
        authoritative_domains=tuple(
            DataDomain(str(item))
            for item in payload.get("authoritative_domains", ())
        ),
        credential_environment_variables=tuple(
            str(item)
            for item in payload.get(
                "credential_environment_variables",
                (),
            )
        ),
        usage_rights_approved=_payload_bool(payload, "usage_rights_approved"),
        point_in_time_supported=_payload_bool(payload, "point_in_time_supported"),
        historical_coverage_supported=_payload_bool(
            payload, "historical_coverage_supported"
        ),
        provenance_complete=_payload_bool(payload, "provenance_complete"),
        service_level_defined=_payload_bool(payload, "service_level_defined"),
        storage_and_backup_approved=_payload_bool(
            payload, "storage_and_backup_approved"
        ),
        derived_analytics_approved=_payload_bool(
            payload, "derived_analytics_approved"
        ),
        paper_simulation_approved=_payload_bool(
            payload, "paper_simulation_approved"
        ),
        certification_required=_payload_bool(payload, "certification_required"),
        certification_identifier=(
            None
            if payload.get("certification_identifier") is None
            else str(payload["certification_identifier"])
        ),
        limitations=tuple(str(item) for item in payload.get("limitations", ())),
    )


def market_scope_from_payload(payload: Mapping[str, Any]) -> MarketDataScope:
    requirements = tuple(
        DatasetCoverageRequirement(
            domain=DataDomain(str(item["domain"])),
            provider_identifiers=tuple(
                str(provider)
                for provider in item["provider_identifiers"]
            ),
            minimum_ready_providers=int(
                item.get("minimum_ready_providers", 1)
            ),
            authoritative_required=_payload_bool(
                item, "authoritative_required", default=True
            ),
        )
        for item in payload.get("requirements", ())
    )
    return MarketDataScope(
        asset_class=CandidateAssetClass(str(payload["asset_class"])),
        state=MarketDataScopeState(str(payload["state"])),
        requirements=requirements,
        rationale=str(payload["rationale"]),
    )


def manifest_from_payload(payload: Mapping[str, Any]) -> AllMarketsDataManifest:
    """Build and validate an all-markets data manifest from JSON-compatible data."""

    if not isinstance(payload, Mapping):
        raise TypeError("data-readiness manifest must be an object")
    return AllMarketsDataManifest(
        identifier=str(payload["identifier"]),
        schema_version=str(
            payload.get("schema_version", "all-markets-data-manifest.v1")
        ),
        reporting_currency=str(payload.get("reporting_currency", "USD")),
        require_complete_candidate_scope=_payload_bool(
            payload, "require_complete_candidate_scope", default=True
        ),
        providers=tuple(
            provider_capability_from_payload(item)
            for item in payload["providers"]
        ),
        markets=tuple(
            market_scope_from_payload(item) for item in payload["markets"]
        ),
    )


def load_data_readiness_manifest(
    path: str | Path,
) -> AllMarketsDataManifest:
    """Read a version-controlled manifest without resolving any secrets."""

    manifest_path = Path(path).expanduser()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DataReadinessError(
            f"cannot read data-readiness manifest {str(manifest_path)!r}"
        ) from error
    try:
        return manifest_from_payload(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise DataReadinessError(
            f"invalid data-readiness manifest {str(manifest_path)!r}: {error}"
        ) from error


