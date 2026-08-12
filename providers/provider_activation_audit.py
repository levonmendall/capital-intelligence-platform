"""Credential-safe audit of whether configured data sources are actually routed.

This is intentionally separate from provider health checks. A provider can be healthy
and still be unused if its credential/configuration never reaches a production consumer.
The audit reports only booleans and environment-variable *names*; it never returns a
credential value.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from provider_environment import (
    PROVIDER_ENVIRONMENT_ALIASES,
    normalize_provider_environment,
)


@dataclass(frozen=True, slots=True)
class ProviderActivationSpec:
    provider_id: str
    evidence_roles: tuple[str, ...]
    production_route: str | None
    credential_groups: tuple[str, ...] = ()
    keyless: bool = False
    note: str = ""
    configuration_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderActivationRecord:
    provider_id: str
    evidence_roles: tuple[str, ...]
    production_route: str | None
    credential_required: bool
    credential_configured: bool
    keyless: bool
    state: str
    credential_names: tuple[str, ...]
    note: str
    configuration_required: bool = False
    configuration_configured: bool = True
    configuration_names: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CORE_PROVIDER_ACTIVATION_SPECS: tuple[ProviderActivationSpec, ...] = (
    ProviderActivationSpec(
        "alpaca-market-data",
        (
            "us_equity_market_data",
            "option_underlying_market_data",
            "option_reference",
            "option_history",
            "crypto_history",
        ),
        "batched U.S. equity/crypto history and opportunity-complete indicative option evidence",
        ("ALPACA_MARKET_DATA_API_KEY", "ALPACA_MARKET_DATA_API_SECRET"),
        note=(
            "Alpaca indicative options are explicitly identified as indicative rather than OPRA; "
            "provider lineage remains attached to governed evidence."
        ),
    ),
    ProviderActivationSpec(
        "massive",
        (
            "option_reference",
            "option_history",
            "us_equity_history",
            "fx_history",
            "crypto_history",
            "us_futures_reference",
            "us_futures_history",
        ),
        "bounded option tertiary fallback and capability-scoped all-asset market-history redundancy",
        ("MASSIVE_API_KEY",),
    ),
    ProviderActivationSpec(
        "eodhd",
        ("global_reference", "multi_asset_market_data", "fixed_income_market_data"),
        "cache-first comprehensive all-market catalog and international market evidence",
        ("EODHD_API_KEY",),
    ),
    ProviderActivationSpec(
        "twelve-data",
        ("global_reference", "fx_reference", "crypto_reference", "supplemental_quote"),
        "comprehensive reference discovery and supplemental quote/evidence redundancy",
        ("TWELVE_DATA_API_KEY",),
    ),
    ProviderActivationSpec(
        "alpha-vantage",
        ("supplemental_quote",),
        "supplemental quote cross-check",
        ("ALPHA_VANTAGE_API_KEY",),
    ),
    ProviderActivationSpec(
        "tradier",
        (
            "supplemental_quote",
            "us_equity_market_data",
            "us_equity_history",
            "us_option_market_data",
            "option_history",
            "active_option_chain_corroboration",
        ),
        "supplemental quote, equity-history failover, active option history, and option-chain corroboration",
        ("TRADIER_API_KEY",),
        note=(
            "Tradier supplies governed U.S. equity/options market evidence only; it has no "
            "execution authority in the Capital Intelligence Platform."
        ),
    ),
    ProviderActivationSpec(
        "openfigi",
        ("security_identity",),
        "OpenFIGI security-identity adapter",
        ("OPENFIGI_API_KEY",),
        note="API key is optional for some OpenFIGI access modes but increases usable capacity.",
    ),
    ProviderActivationSpec(
        "coinbase",
        ("crypto_quote_validation", "crypto_history"),
        "independent crypto venue quote validation and native history evidence adapter",
        keyless=True,
    ),
    ProviderActivationSpec(
        "kraken",
        ("crypto_quote_validation", "crypto_history"),
        "independent crypto venue quote validation and native history evidence adapter",
        keyless=True,
    ),
    ProviderActivationSpec(
        "fred",
        ("macro",),
        "governed public-live information runtime",
        ("FRED_API_KEY",),
    ),
    ProviderActivationSpec(
        "bea",
        ("macro",),
        "governed public-live information runtime",
        ("BEA_API_KEY",),
    ),
    ProviderActivationSpec(
        "census",
        ("macro",),
        "governed public-live information runtime",
        ("CENSUS_API_KEY",),
    ),
    ProviderActivationSpec(
        "eia",
        ("energy", "macro"),
        "governed public-live information runtime",
        ("EIA_API_KEY",),
    ),
    ProviderActivationSpec(
        "usda-nass",
        ("agriculture", "macro"),
        "governed public-live information runtime",
        ("USDA_NASS_API_KEY",),
    ),
    ProviderActivationSpec(
        "nasa-firms",
        ("physical_risk",),
        "governed public-live information runtime",
        ("NASA_FIRMS_MAP_KEY",),
    ),
    ProviderActivationSpec(
        "sec-edgar",
        ("fundamentals", "corporate_filings"),
        "governed SEC information adapters",
        keyless=True,
    ),
    ProviderActivationSpec(
        "gleif",
        ("entity_identity",),
        "GLEIF legal-entity identity adapter",
        keyless=True,
    ),
    ProviderActivationSpec(
        "treasury-fiscal-data",
        ("treasury_security_reference",),
        "fixed-income Treasury CUSIP/reference enrichment",
        keyless=True,
    ),
    ProviderActivationSpec(
        "finra",
        ("fixed_income_market_structure", "trace", "specialist_environment_context"),
        "governed public-live fixed-income specialist/environment context",
        ("FINRA_CLIENT_ID", "FINRA_CLIENT_SECRET"),
        note=(
            "FINRA aggregate TRACE context is routed to specialist/environment evidence only; "
            "it cannot satisfy individual-bond identity, price, history, valuation, or execution."
        ),
    ),
    ProviderActivationSpec(
        "cme-margin-data",
        ("derivative_margin_data",),
        "all-market readiness CME DataMine SPAN/SPAN 2 resource preflight",
        credential_groups=(
            "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_ID",
            "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_PASSWORD",
        ),
        configuration_groups=(
            "CAPITAL_INTELLIGENCE_CME_MARGIN_BINDING",
            "CAPITAL_INTELLIGENCE_CME_MARGIN_TERMS_REFERENCE",
            "CAPITAL_INTELLIGENCE_CME_MARGIN_PAPER_USE_APPROVAL",
            "CAPITAL_INTELLIGENCE_CME_MARGIN_CERTIFICATION_ID",
        ),
        note=(
            "Production CME SPAN access is authenticated through the DataMine API. The "
            "repository binding contains the governed CME file-ID catalog; terms/paper-use "
            "approval, certification, preflight validation, and append-only activation remain required."
        ),
    ),
    ProviderActivationSpec(
        "occ-margin-data",
        ("derivative_margin_data",),
        "all-market readiness clearing-risk resource preflight",
        keyless=True,
        configuration_groups=(
            "CAPITAL_INTELLIGENCE_OCC_MARGIN_BINDING",
            "CAPITAL_INTELLIGENCE_OCC_MARGIN_TERMS_REFERENCE",
            "CAPITAL_INTELLIGENCE_OCC_MARGIN_PAPER_USE_APPROVAL",
            "CAPITAL_INTELLIGENCE_OCC_MARGIN_CERTIFICATION_ID",
        ),
        note=(
            "OCC OFRA is public/keyless clearing-risk evidence but still requires the "
            "governed binding, approval, certification, and activation path."
        ),
    ),
    ProviderActivationSpec(
        "derived-volatility-surfaces",
        ("volatility_surface_data",),
        "canonical option-quote volatility-surface compiler and all-market readiness",
        keyless=True,
        configuration_groups=(
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_BINDING",
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_MODEL_APPROVAL",
            "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_CERTIFICATION_ID",
        ),
        note=(
            "The compiler can produce surfaces from canonical option quotes, but compilation "
            "cannot self-approve or self-certify the model."
        ),
    ),
)


_BUNDLE_PROVIDER_FAMILIES_WITH_DIRECT_ROUTES = frozenset(
    {
        "eodhd-primary",
        "coinbase-crypto-validation",
        "kraken-crypto-validation",
        "cme-margin-data",
        "occ-margin-data",
        "derived-volatility-surfaces",
    }
)


def _group_names(canonical: str) -> tuple[str, ...]:
    return (canonical, *PROVIDER_ENVIRONMENT_ALIASES.get(canonical, ()))


def _group_is_configured(environment: Mapping[str, str], canonical: str) -> bool:
    return any(
        isinstance(environment.get(name), str) and bool(environment[name].strip())
        for name in _group_names(canonical)
    )


def _names(groups: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    for canonical in groups:
        names.extend(_group_names(canonical))
    return tuple(dict.fromkeys(names))


def _configured_dataset_specs(root: Path) -> tuple[ProviderActivationSpec, ...]:
    """Expose institutional bundle members that are easy to mistake as CIO-routed."""

    path = root / "config" / "all_market_provider_bundle.json"
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    members = payload.get("members") if isinstance(payload, Mapping) else None
    if not isinstance(members, list):
        return ()
    specs: list[ProviderActivationSpec] = []
    for raw in members:
        if not isinstance(raw, Mapping):
            continue
        provider_id = str(raw.get("provider_identifier", "")).strip()
        if not provider_id or provider_id in _BUNDLE_PROVIDER_FAMILIES_WITH_DIRECT_ROUTES:
            continue
        roles = raw.get("roles")
        evidence_roles = tuple(
            str(item).strip() for item in roles if str(item).strip()
        ) if isinstance(roles, list) else ()
        credentials = raw.get("credential_environment_variables")
        credential_groups = tuple(
            str(item).strip() for item in credentials if str(item).strip()
        ) if isinstance(credentials, list) else ()
        configuration_groups: list[str] = []
        for field in (
            "binding_environment_variables",
            "contract_reference_environment_variables",
            "license_approval_environment_variables",
            "certification_environment_variables",
        ):
            values = raw.get(field)
            if isinstance(values, list):
                configuration_groups.extend(
                    str(item).strip() for item in values if str(item).strip()
                )
        specs.append(
            ProviderActivationSpec(
                provider_id=provider_id,
                evidence_roles=evidence_roles,
                production_route=None,
                credential_groups=credential_groups,
                keyless=not credential_groups,
                configuration_groups=tuple(dict.fromkeys(configuration_groups)),
                note=(
                    "Declared in all_market_provider_bundle.json, but no direct comprehensive-"
                    "discovery consumer is declared by the activation registry. Bundle readiness "
                    "must not be mistaken for CIO-path consumption."
                ),
            )
        )
    return tuple(specs)


def audit_provider_activation(
    environment: Mapping[str, str] | None = None,
    *,
    repository_root: str | Path | None = None,
) -> tuple[ProviderActivationRecord, ...]:
    """Return credential-safe activation state for known provider capabilities."""

    env = normalize_provider_environment(os.environ if environment is None else environment)
    root = Path(repository_root or Path(__file__).resolve().parents[1])
    specs = (*CORE_PROVIDER_ACTIVATION_SPECS, *_configured_dataset_specs(root))
    records: list[ProviderActivationRecord] = []
    for spec in specs:
        credential_names = _names(spec.credential_groups)
        configuration_names = _names(spec.configuration_groups)
        credential_required = bool(spec.credential_groups) and not spec.keyless
        configuration_required = bool(spec.configuration_groups)
        credential_configured = (
            True
            if not spec.credential_groups
            else all(_group_is_configured(env, group) for group in spec.credential_groups)
        )
        configuration_configured = (
            True
            if not spec.configuration_groups
            else all(_group_is_configured(env, group) for group in spec.configuration_groups)
        )
        fully_configured = credential_configured and configuration_configured
        if spec.production_route is None:
            state = "configured_but_unrouted" if fully_configured else "unrouted"
        elif credential_required and not credential_configured:
            state = "missing_credential"
        elif configuration_required and not configuration_configured:
            state = "missing_configuration"
        elif spec.keyless:
            state = "keyless_active"
        else:
            state = "active"
        records.append(
            ProviderActivationRecord(
                provider_id=spec.provider_id,
                evidence_roles=spec.evidence_roles,
                production_route=spec.production_route,
                credential_required=credential_required,
                credential_configured=credential_configured,
                keyless=spec.keyless,
                state=state,
                credential_names=credential_names,
                note=spec.note,
                configuration_required=configuration_required,
                configuration_configured=configuration_configured,
                configuration_names=configuration_names,
            )
        )
    return tuple(sorted(records, key=lambda item: item.provider_id))


def activation_summary(
    environment: Mapping[str, str] | None = None,
    *,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    records = audit_provider_activation(
        environment,
        repository_root=repository_root,
    )
    states = sorted({item.state for item in records})
    return {
        "schema_version": "provider-activation-audit.v2",
        "credential_values_included": False,
        "providers": [item.to_dict() for item in records],
        "counts": {
            state: sum(1 for item in records if item.state == state)
            for state in states
        },
        "unrouted_provider_ids": [
            item.provider_id
            for item in records
            if item.state in {"configured_but_unrouted", "unrouted"}
        ],
        "missing_credential_provider_ids": [
            item.provider_id for item in records if item.state == "missing_credential"
        ],
        "missing_configuration_provider_ids": [
            item.provider_id for item in records if item.state == "missing_configuration"
        ],
    }


def main() -> int:
    print(json.dumps(activation_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CORE_PROVIDER_ACTIVATION_SPECS",
    "ProviderActivationRecord",
    "ProviderActivationSpec",
    "activation_summary",
    "audit_provider_activation",
]
