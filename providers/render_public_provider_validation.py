"""Credential-safe runtime validation for public providers configured in Render.

The report proves only that expected environment variables are present and that a
bounded authenticated request or the operating public-source collection succeeded.
It never exposes secret values, grants provider certification, changes data
readiness, or authorizes an investment or execution action.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping

from providers.openfigi import OpenFigiMappingJob, OpenFigiProvider
from providers.provider_credentials import (
    AlphaVantageCredentialProbe,
    ProviderCredentialProbeError,
    TwelveDataCredentialProbe,
    configured_environment_names,
    environment_credential,
)


_RENDER_PUBLIC_PROVIDERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("openfigi", "OpenFIGI", ("OPENFIGI_API_KEY", "OPEN_FIGI_API_KEY")),
    (
        "alpha-vantage",
        "Alpha Vantage",
        AlphaVantageCredentialProbe.environment_names,
    ),
    ("twelve-data", "Twelve Data", TwelveDataCredentialProbe.environment_names),
    ("bea", "U.S. Bureau of Economic Analysis", ("BEA_API_KEY",)),
    ("census", "U.S. Census Bureau", ("CENSUS_API_KEY",)),
    ("usda-nass", "USDA NASS Quick Stats", ("USDA_NASS_API_KEY",)),
    ("eia", "U.S. Energy Information Administration", ("EIA_API_KEY",)),
    ("nasa-firms", "NASA FIRMS", ("NASA_FIRMS_MAP_KEY",)),
)


def _safe_error(error: Exception, aliases: tuple[str, ...]) -> str:
    message = str(error).strip() or type(error).__name__
    for name in aliases:
        value = os.getenv(name, "")
        if value:
            message = message.replace(value, "[REDACTED]")
    return message


def _redacted_text(value: object, aliases: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    return _safe_error(RuntimeError(str(value)), aliases)


def _supplemental_probe(provider: str, aliases: tuple[str, ...]) -> dict[str, Any]:
    configured_names = configured_environment_names(*aliases)
    result: dict[str, Any] = {
        "configured": bool(configured_names),
        "credential_names": list(configured_names),
        "selected_credential": None,
        "passed": False,
        "evidence": {},
    }
    credential = environment_credential(*aliases)
    if credential is None:
        result["error"] = "no supported Render environment credential is configured"
        return result
    try:
        if provider == "openfigi":
            mappings = OpenFigiProvider(api_key=credential.value).map_identifiers(
                (
                    OpenFigiMappingJob(
                        id_type="ID_BB_GLOBAL",
                        id_value="BBG000B9XRY4",
                    ),
                )
            )
            matches = mappings[0].matches
            if not matches:
                raise ProviderCredentialProbeError(
                    "OpenFIGI returned no authenticated mapping matches"
                )
            evidence = {
                "probe": "v3-mapping",
                "requested_identifier": "BBG000B9XRY4",
                "match_count": len(matches),
            }
        elif provider == "alpha-vantage":
            evidence = AlphaVantageCredentialProbe(credential.value).probe()
        elif provider == "twelve-data":
            evidence = TwelveDataCredentialProbe(credential.value).probe()
        else:
            raise ValueError(f"unsupported supplemental provider {provider!r}")
    except Exception as error:  # bounded external provider boundary
        result["error"] = _safe_error(error, aliases)
        return result
    result.update(
        {
            "passed": True,
            "selected_credential": credential.name,
            "evidence": evidence,
        }
    )
    return result


def _catalog_results(
    *,
    aliases: tuple[str, ...],
    catalog: object,
    coverage_report: object,
) -> dict[str, Any]:
    sources = tuple(getattr(catalog, "sources", ()) or ())
    definitions = tuple(
        item
        for item in sources
        if set(getattr(item, "credential_environment_variables", ()) or ())
        .intersection(aliases)
    )
    source_identifiers = {
        str(getattr(item, "identifier", ""))
        for item in definitions
        if str(getattr(item, "identifier", "")).strip()
    }
    observed = tuple(
        item
        for item in tuple(getattr(coverage_report, "sources", ()) or ())
        if str(getattr(item, "source_identifier", "")) in source_identifiers
    )
    passed = any(bool(getattr(item, "succeeded", False)) for item in observed)
    errors = tuple(
        _redacted_text(
            getattr(item, "error", "source request failed"),
            aliases,
        )
        for item in observed
        if not bool(getattr(item, "succeeded", False))
    )
    configured_names = configured_environment_names(*aliases)
    payload: dict[str, Any] = {
        "configured": bool(configured_names),
        "credential_names": list(configured_names),
        "selected_credential": (
            configured_names[0] if configured_names else None
        ),
        "passed": passed,
        "evidence": {
            "validation_path": "operating-public-source-collection",
            "source_identifiers": sorted(source_identifiers),
            "observed_source_count": len(observed),
            "successful_source_count": sum(
                bool(getattr(item, "succeeded", False)) for item in observed
            ),
            "record_count": sum(
                int(getattr(item, "record_count", 0) or 0) for item in observed
            ),
        },
    }
    if not configured_names:
        payload["error"] = "no supported Render environment credential is configured"
    elif not definitions:
        payload["error"] = "credential is configured but no operating source is mapped"
    elif not observed:
        payload["error"] = "mapped operating source was not observed in this collection"
    elif not passed:
        payload["error"] = "; ".join(item for item in errors if item) or (
            "all mapped source requests failed"
        )
    return payload


def build_render_public_provider_validation(
    *,
    catalog: object,
    coverage_report: object,
    evaluated_at: datetime | None = None,
    supplemental_results: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one redacted validation report for the eight configured public keys."""

    as_of = evaluated_at or datetime.now(timezone.utc)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    supplied = dict(supplemental_results or {})
    providers: list[dict[str, Any]] = []
    for identifier, name, aliases in _RENDER_PUBLIC_PROVIDERS:
        if identifier in {"openfigi", "alpha-vantage", "twelve-data"}:
            result = dict(
                supplied.get(identifier)
                or _supplemental_probe(identifier, aliases)
            )
        else:
            result = _catalog_results(
                aliases=aliases,
                catalog=catalog,
                coverage_report=coverage_report,
            )
        configured = bool(result.get("configured"))
        passed = bool(result.get("passed"))
        providers.append(
            {
                "provider": identifier,
                "display_name": name,
                "configured": configured,
                "credential_names": list(result.get("credential_names", ())),
                "selected_credential": result.get("selected_credential"),
                "authentication_validated": passed,
                "state": (
                    "validated"
                    if passed
                    else ("validation_failed" if configured else "missing_configuration")
                ),
                "evidence": dict(result.get("evidence", {})),
                "error": _redacted_text(result.get("error"), aliases),
                "provider_certified": False,
                "decision_evidence_authority": False,
                "execution_authority": False,
                "real_money_authorized": False,
            }
        )
    configured_count = sum(item["configured"] for item in providers)
    validated_count = sum(item["authentication_validated"] for item in providers)
    missing = tuple(
        item["provider"] for item in providers if not item["configured"]
    )
    failed = tuple(
        item["provider"]
        for item in providers
        if item["configured"] and not item["authentication_validated"]
    )
    state = "validated"
    if missing:
        state = "blocked"
    elif failed:
        state = "degraded"
    return {
        "schema_version": "render-public-provider-validation.v1",
        "identifier": f"render-public-provider-validation:{as_of.isoformat()}",
        "evaluated_at": as_of.astimezone(timezone.utc).isoformat(),
        "state": state,
        "provider_count": len(providers),
        "configured_provider_count": configured_count,
        "validated_provider_count": validated_count,
        "missing_configuration": list(missing),
        "validation_failures": list(failed),
        "providers": providers,
        "secret_values_disclosed": False,
        "provider_certification_granted": False,
        "data_readiness_granted": False,
        "decision_evidence_authority": False,
        "paper_test_authorized": False,
        "execution_authority_granted": False,
        "real_money_authorized": False,
    }


__all__ = ["build_render_public_provider_validation"]
