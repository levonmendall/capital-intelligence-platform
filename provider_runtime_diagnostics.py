"""Credential-safe provider availability diagnostics across deployment environments."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from provider_environment import normalize_provider_environment


@dataclass(frozen=True, slots=True)
class ProviderRuntimeDefinition:
    identifier: str
    pipeline_role: str
    credential_groups: tuple[tuple[str, ...], ...] = ()
    binding_variables: tuple[str, ...] = ()
    default_binding_paths: tuple[str, ...] = ()
    contract_variables: tuple[str, ...] = ()
    license_variables: tuple[str, ...] = ()
    certification_variables: tuple[str, ...] = ()
    keyless: bool = False
    canonical_ingestion: bool = False
    paper_execution: bool = False


PROVIDER_RUNTIME_DEFINITIONS: tuple[ProviderRuntimeDefinition, ...] = (
    ProviderRuntimeDefinition(
        identifier="alpaca_paper",
        pipeline_role="paper_execution_and_quotes",
        credential_groups=(
            ("APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY"),
            (
                "APCA_API_SECRET_KEY",
                "ALPACA_API_SECRET_KEY",
                "ALPACA_SECRET_KEY",
                "ALPACA_API_SECRET",
            ),
        ),
        canonical_ingestion=True,
        paper_execution=True,
    ),
    ProviderRuntimeDefinition(
        identifier="fred",
        pipeline_role="official_macro",
        credential_groups=(("FRED_API_KEY",),),
        certification_variables=("CAPITAL_INTELLIGENCE_FRED_CERTIFICATION_IDENTIFIER",),
        canonical_ingestion=True,
    ),
    ProviderRuntimeDefinition(
        identifier="sec_edgar",
        pipeline_role="official_filings",
        credential_groups=(("SEC_USER_AGENT",),),
        certification_variables=("CAPITAL_INTELLIGENCE_SEC_CERTIFICATION_IDENTIFIER",),
        canonical_ingestion=True,
    ),
    ProviderRuntimeDefinition(
        identifier="databento",
        pipeline_role="execution_grade_market_and_derivative_data",
        credential_groups=(
            ("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY", "DATABENTO_API_KEY"),
        ),
        binding_variables=(
            "CAPITAL_INTELLIGENCE_DATABENTO_INSTRUMENT_BINDINGS",
            "CAPITAL_INTELLIGENCE_DATABENTO_BINDING",
        ),
        default_binding_paths=(
            "config/databento_instrument_bindings.all_markets.json",
        ),
        contract_variables=("CAPITAL_INTELLIGENCE_DATABENTO_CONTRACT_REFERENCE",),
        license_variables=("CAPITAL_INTELLIGENCE_DATABENTO_LICENSE_APPROVAL",),
        certification_variables=("CAPITAL_INTELLIGENCE_DATABENTO_CERTIFICATION_ID",),
        canonical_ingestion=True,
    ),
    ProviderRuntimeDefinition(
        identifier="eodhd",
        pipeline_role="broad_historical_multi_asset",
        credential_groups=(
            (
                "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
                "EODHD_API_KEY",
                "EODHD_API_TOKEN",
            ),
        ),
        binding_variables=("CAPITAL_INTELLIGENCE_EODHD_BINDINGS",),
        default_binding_paths=("config/eodhd_instrument_bindings.all_markets.json",),
        contract_variables=("CAPITAL_INTELLIGENCE_EODHD_CONTRACT_REFERENCE",),
        license_variables=("CAPITAL_INTELLIGENCE_EODHD_LICENSE_APPROVAL",),
        certification_variables=("CAPITAL_INTELLIGENCE_EODHD_CERTIFICATION_ID",),
        canonical_ingestion=True,
    ),
    ProviderRuntimeDefinition(
        identifier="openfigi",
        pipeline_role="supporting_identity_mapping",
        credential_groups=(("OPENFIGI_API_KEY", "OPEN_FIGI_API_KEY"),),
    ),
    ProviderRuntimeDefinition(
        identifier="alpha_vantage",
        pipeline_role="supplemental_quote_crosscheck",
        credential_groups=(("ALPHAVANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY"),),
    ),
    ProviderRuntimeDefinition(
        identifier="twelve_data",
        pipeline_role="supplemental_quote_crosscheck",
        credential_groups=(("TWELVE_API_KEY", "TWELVE_DATA_API_KEY"),),
    ),
    ProviderRuntimeDefinition(
        identifier="coinbase_exchange",
        pipeline_role="independent_crypto_validation",
        keyless=True,
        contract_variables=("CAPITAL_INTELLIGENCE_COINBASE_TERMS_REFERENCE",),
        license_variables=("CAPITAL_INTELLIGENCE_COINBASE_PAPER_USE_APPROVAL",),
        certification_variables=("CAPITAL_INTELLIGENCE_COINBASE_CERTIFICATION_ID",),
        canonical_ingestion=True,
    ),
    ProviderRuntimeDefinition(
        identifier="kraken_spot",
        pipeline_role="independent_crypto_validation",
        keyless=True,
        contract_variables=("CAPITAL_INTELLIGENCE_KRAKEN_TERMS_REFERENCE",),
        license_variables=("CAPITAL_INTELLIGENCE_KRAKEN_PAPER_USE_APPROVAL",),
        certification_variables=("CAPITAL_INTELLIGENCE_KRAKEN_CERTIFICATION_ID",),
        canonical_ingestion=True,
    ),
)


def detect_runtime_context(environment: Mapping[str, str] | None = None) -> str:
    source = os.environ if environment is None else environment
    if str(source.get("GITHUB_ACTIONS", "")).lower() == "true":
        return "github_actions"
    streamlit_markers = (
        "STREAMLIT_SERVER_PORT",
        "STREAMLIT_SHARING_MODE",
        "STREAMLIT_RUNTIME",
        "IS_STREAMLIT_CLOUD",
    )
    if any(str(source.get(name, "")).strip() for name in streamlit_markers):
        return "streamlit_runtime"
    return "local_runtime"


def _selected_name(environment: Mapping[str, str], aliases: Sequence[str]) -> str | None:
    for name in aliases:
        value = environment.get(name)
        if isinstance(value, str) and value.strip():
            return name
    return None


def _binding_paths(
    definition: ProviderRuntimeDefinition,
    environment: Mapping[str, str],
) -> tuple[Path, ...]:
    paths: list[Path] = []
    for variable in definition.binding_variables:
        value = environment.get(variable)
        if isinstance(value, str) and value.strip():
            paths.append(Path(value.strip()).expanduser())
    if not paths:
        paths.extend(Path(value) for value in definition.default_binding_paths)
    return tuple(paths)


def build_provider_runtime_report(
    *,
    environment: Mapping[str, str] | None = None,
    environment_name: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_provider_environment(environment)
    context = environment_name or detect_runtime_context(normalized)
    providers: list[dict[str, Any]] = []
    for definition in PROVIDER_RUNTIME_DEFINITIONS:
        selected_credentials = [
            selected
            for group in definition.credential_groups
            if (selected := _selected_name(normalized, group)) is not None
        ]
        credentials_ready = definition.keyless or len(selected_credentials) == len(
            definition.credential_groups
        )
        paths = _binding_paths(definition, normalized)
        binding_required = bool(definition.binding_variables or definition.default_binding_paths)
        existing_paths = tuple(path for path in paths if path.exists() and path.is_file())
        binding_ready = not binding_required or bool(existing_paths)
        contract_present = bool(_selected_name(normalized, definition.contract_variables))
        license_present = bool(_selected_name(normalized, definition.license_variables))
        certification_present = bool(
            _selected_name(normalized, definition.certification_variables)
        )
        blockers: list[str] = []
        if not credentials_ready:
            blockers.append("credential_missing")
        if not binding_ready:
            blockers.append("runtime_binding_missing")
        runtime_ready = credentials_ready and binding_ready
        providers.append(
            {
                "provider": definition.identifier,
                "pipeline_role": definition.pipeline_role,
                "runtime_context": context,
                "credential_state": "configured" if credentials_ready else "missing",
                "selected_credential_names": selected_credentials,
                "binding_state": "configured" if binding_ready else "missing",
                "binding_paths": [str(path) for path in paths],
                "existing_binding_paths": [str(path) for path in existing_paths],
                "runtime_ready": runtime_ready,
                "canonical_ingestion": definition.canonical_ingestion,
                "paper_execution": definition.paper_execution,
                "contract_reference_present": contract_present,
                "license_approval_input_present": license_present,
                "certification_input_present": certification_present,
                "provider_activation_granted": False,
                "blockers": blockers,
            }
        )
    configured = [item for item in providers if item["runtime_ready"]]
    blockers = [
        f"{item['provider']}:{blocker}"
        for item in providers
        for blocker in item["blockers"]
    ]
    return {
        "schema_version": "provider-runtime-diagnostics.v1",
        "environment_name": context,
        "runtime_context": detect_runtime_context(normalized),
        "provider_count": len(providers),
        "runtime_ready_provider_count": len(configured),
        "state": "ready" if not blockers else "partial",
        "blockers": blockers,
        "providers": providers,
        "secret_values_disclosed": False,
        "real_money_authorized": False,
    }


def merge_runtime_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for report in reports:
        environment_name = str(report.get("environment_name") or "unknown")
        sources.append(environment_name)
        providers = report.get("providers")
        if not isinstance(providers, list):
            raise ValueError("runtime report providers must be a list")
        for item in providers:
            if not isinstance(item, Mapping):
                raise ValueError("runtime provider entries must be objects")
            provider = str(item.get("provider") or "").strip()
            if not provider:
                raise ValueError("runtime provider entry is missing provider")
            row = matrix.setdefault(
                provider,
                {
                    "provider": provider,
                    "pipeline_role": item.get("pipeline_role"),
                    "availability_by_environment": {},
                },
            )
            row["availability_by_environment"][environment_name] = {
                "runtime_ready": bool(item.get("runtime_ready")),
                "credential_state": item.get("credential_state"),
                "binding_state": item.get("binding_state"),
                "blockers": list(item.get("blockers") or []),
            }
    return {
        "schema_version": "provider-runtime-matrix.v1",
        "environments": list(dict.fromkeys(sources)),
        "providers": sorted(matrix.values(), key=lambda item: item["provider"]),
        "secret_values_disclosed": False,
        "real_money_authorized": False,
    }


def load_report(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("runtime report must be a JSON object")
    return payload


__all__ = [
    "PROVIDER_RUNTIME_DEFINITIONS",
    "ProviderRuntimeDefinition",
    "build_provider_runtime_report",
    "detect_runtime_context",
    "load_report",
    "merge_runtime_reports",
]
