"""Build a machine-readable audit of decision-information capability gaps.

The audit reconciles the declared maximum-information requirements with the active
public-source catalogs and, when available, the latest runtime collection report.
It is diagnostic only: a source being implemented or reachable never creates
investment authority or paper-allocation capability.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from data.decision_information import InformationSourceType
from governance.information_capability_registry import (
    CoverageScope,
    InformationCapabilityRecord,
    InformationCapabilityRegistry,
)
from providers.public_decision_information import PublicDecisionInformationPolicy
from providers.public_live_source_catalogs import load_operating_public_live_source_catalog


DEFAULT_SCOPE_PATH = Path("config/maximum_decision_information_scope.json")
DEFAULT_PUBLIC_CATALOG_PATH = Path("config/public_live_information_sources.json")


def _load_mapping(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _runtime_health(path: Path | None) -> dict[str, bool]:
    if path is None or not path.exists():
        return {}
    payload = _load_mapping(path)
    rows = payload.get("sources", ())
    if not isinstance(rows, list):
        return {}
    result: dict[str, bool] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        identifier = str(row.get("source_identifier", "")).strip()
        if identifier:
            result[identifier] = bool(row.get("succeeded", False))
    return result


def _credentials(names: tuple[str, ...]) -> tuple[bool, bool]:
    if not names:
        return True, True
    configured = all(str(os.getenv(name, "")).strip() for name in names)
    return configured, configured


def _manifest_capabilities(
    payload: Mapping[str, Any],
) -> tuple[InformationCapabilityRecord, ...]:
    rows = payload.get("sources", ())
    if not isinstance(rows, list):
        raise ValueError("maximum-information scope sources must be an array")
    records: list[InformationCapabilityRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("maximum-information source entries must be objects")
        identifier = str(row.get("identifier", "")).strip()
        domains = tuple(str(item) for item in row.get("domains", ()) if str(item).strip())
        if not identifier or not domains:
            continue
        credential_names = tuple(
            str(item).strip().upper()
            for item in row.get("credential_environment_variables", ())
            if str(item).strip()
        )
        configured, credentialed = _credentials(credential_names)
        enabled = bool(row.get("enabled", False))
        point_in_time = bool(
            row.get("availability_time_supported", False)
            and row.get("provenance_complete", False)
        )
        certification_required = bool(row.get("certification_required", True))
        static_certified = bool(
            enabled
            and configured
            and point_in_time
            and row.get("usage_rights_approved", False)
            and (not certification_required or row.get("certification_identifier"))
        )
        records.append(
            InformationCapabilityRecord(
                identifier=f"manifest:{identifier}",
                domains=domains,
                implemented=enabled,
                configured=configured,
                credentialed=credentialed,
                reachable=False,
                collecting=False,
                point_in_time_capable=point_in_time,
                historical_capable=bool(row.get("historical_coverage_supported", False)),
                decision_certified=False,
                allocatable=False,
                healthy=False,
                source_independence_group=str(
                    row.get("independence_group", identifier)
                ),
                limitations=tuple(
                    dict.fromkeys(
                        (
                            *tuple(str(item) for item in row.get("limitations", ())),
                            *(
                                ("Static manifest is certification-eligible but runtime health is not established.",)
                                if static_certified
                                else ()
                            ),
                        )
                    )
                ),
            )
        )
    return tuple(records)


def build_information_gap_audit(
    *,
    scope_path: str | Path = DEFAULT_SCOPE_PATH,
    public_catalog_path: str | Path = DEFAULT_PUBLIC_CATALOG_PATH,
    runtime_report_path: str | Path | None = None,
) -> dict[str, object]:
    scope = _load_mapping(Path(scope_path))
    catalog = load_operating_public_live_source_catalog(public_catalog_path)
    runtime = _runtime_health(
        None if runtime_report_path is None else Path(runtime_report_path)
    )
    public_policy = PublicDecisionInformationPolicy()
    records = list(_manifest_capabilities(scope))
    for source in catalog.sources:
        configured = source.configured
        reachable = runtime.get(source.identifier, False)
        policy_eligible = (
            source.source_type
            in {
                InformationSourceType.OFFICIAL,
                InformationSourceType.REGULATORY,
                InformationSourceType.ISSUER,
                InformationSourceType.MARKET,
            }
            and source.reliability >= public_policy.minimum_reliability
            and source.relevance >= public_policy.minimum_relevance
            and source.materiality >= public_policy.minimum_materiality
        )
        records.append(
            InformationCapabilityRecord(
                identifier=f"public:{source.identifier}",
                domains=source.domains,
                implemented=source.enabled,
                configured=configured,
                credentialed=(configured or not source.credential_environment_variables),
                reachable=reachable,
                collecting=reachable,
                point_in_time_capable=True,
                historical_capable=False,
                decision_certified=bool(reachable and policy_eligible),
                allocatable=False,
                healthy=reachable,
                source_independence_group=source.independence_group,
                limitations=source.limitations,
            )
        )
    registry = InformationCapabilityRegistry(tuple(records))
    requirements = scope.get("requirements", ())
    if not isinstance(requirements, list):
        raise ValueError("maximum-information requirements must be an array")
    required_domains = tuple(
        dict.fromkeys(
            str(item.get("domain", "")).strip()
            for item in requirements
            if isinstance(item, Mapping) and str(item.get("domain", "")).strip()
        )
    )
    gaps = registry.gaps(
        required_domains,
        required_scope=CoverageScope.DECISION_CERTIFIED,
    )
    domain_status = []
    for domain in required_domains:
        capabilities = registry.for_domain(domain)
        domain_status.append(
            {
                "domain": domain,
                "monitored": registry.coverage(
                    domain, required_scope=CoverageScope.MONITORED
                ),
                "decision_certified_and_healthy": registry.coverage(domain),
                "capability_identifiers": [item.identifier for item in capabilities],
                "historical_capability_present": any(
                    item.historical_capable for item in capabilities
                ),
            }
        )
    return {
        "schema_version": "information-gap-audit.v1",
        "scope_identifier": str(scope.get("identifier", "unknown")),
        "public_catalog_identifier": catalog.identifier,
        "runtime_health_supplied": bool(runtime),
        "registry": registry.summary(),
        "required_domain_count": len(required_domains),
        "decision_gap_count": len(gaps),
        "domain_status": domain_status,
        "gaps": [
            {
                **asdict(item),
                "required_scope": item.required_scope.value,
            }
            for item in gaps
        ],
        "investment_authority": False,
        "execution_authority": False,
        "real_money_authorized": False,
    }


__all__ = ["build_information_gap_audit"]
