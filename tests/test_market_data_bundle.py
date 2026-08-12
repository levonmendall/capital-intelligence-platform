from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.data_readiness_core import DataDomain
from governance.market_data_bundle import (
    assess_all_market_provider_bundle,
    load_all_market_provider_bundle,
)
from governance.provider_activation import (
    ProviderActivation,
    SQLiteProviderActivationStore,
)
from run_all_market_provider_bundle import main as bundle_main

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _configured_binding(path: Path, member) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "configured-dataset-provider.v1",
                "provider_identifier": member.provider_identifier,
                "source_version": "certified-test.v1",
                "base_url": "https://licensed-provider.test/normalized/",
                "bindings": [
                    {
                        "dataset_type": item.value,
                        "path": f"v1/{item.value}/{{symbol}}",
                    }
                    for item in member.required_dataset_types
                ],
            }
        ),
        encoding="utf-8",
    )


def _activation(member) -> ProviderActivation:
    domains = tuple(DataDomain(item.value) for item in member.required_dataset_types)
    return ProviderActivation(
        identifier=f"activation:{member.provider_identifier}:test",
        provider_identifier=member.provider_identifier,
        provider_name=member.provider_name,
        enabled=True,
        approved_domains=domains,
        authoritative_domains=domains,
        usage_rights_approved=True,
        point_in_time_supported=True,
        historical_coverage_supported=True,
        provenance_complete=True,
        service_level_defined=True,
        storage_and_backup_approved=True,
        derived_analytics_approved=True,
        paper_simulation_approved=True,
        certification_identifier=f"certification:{member.provider_identifier}:test",
        approved_by="data-governance-committee",
        rationale="Complete provider-bundle activation fixture.",
        approved_at=AS_OF - timedelta(days=2),
        effective_at=AS_OF - timedelta(days=1),
        expires_at=AS_OF + timedelta(days=30),
        source_identifiers=(f"contract:{member.provider_identifier}:test",),
    )


def test_selected_provider_bundle_declares_every_required_operating_role() -> None:
    bundle = load_all_market_provider_bundle(
        "config/all_market_provider_bundle.json"
    )

    assert len(bundle.members) == 12
    assert {item.provider_identifier for item in bundle.members} >= {
        "lseg-global-market-data",
        "lseg-global-reference-data",
        "ice-evaluated-fixed-income",
        "cme-futures-market-data",
        "eodhd-primary",
        "coinbase-crypto-validation",
        "kraken-crypto-validation",
        "cme-margin-data",
        "occ-margin-data",
        "ice-margin-data",
        "derived-volatility-surfaces",
    }


def test_source_templates_remain_fail_closed(tmp_path: Path) -> None:
    bundle = load_all_market_provider_bundle(
        "config/all_market_provider_bundle.json"
    )
    environment: dict[str, str] = {}
    for member in bundle.members:
        for name in (
            member.credential_environment_variables
            + member.contract_reference_environment_variables
            + member.license_approval_environment_variables
            + member.certification_environment_variables
        ):
            environment[name] = "configured-test-value"
        for name in member.binding_environment_variables:
            if member.provider_identifier == "eodhd-primary":
                environment[name] = "config/eodhd_instrument_bindings.all_markets.json"
            elif "crypto" in member.provider_identifier:
                environment[name] = "config/crypto_venue_bindings.all_markets.json"
            else:
                environment[name] = str(
                    Path("config/provider_bindings")
                    / f"{member.provider_identifier.replace('-', '_')}.example.json"
                )

    report = assess_all_market_provider_bundle(
        bundle,
        evaluated_at=AS_OF,
        environment=environment,
        provider_activation_store=SQLiteProviderActivationStore(
            tmp_path / "providers.db"
        ),
    )

    assert report.implementation_ready is True
    assert report.active is False
    assert any(
        "base_url is still a placeholder" in blocker
        for item in report.member_assessments
        for blocker in item.blockers
    )


def test_complete_external_bundle_can_become_active(tmp_path: Path) -> None:
    bundle = load_all_market_provider_bundle(
        "config/all_market_provider_bundle.json"
    )
    store = SQLiteProviderActivationStore(tmp_path / "providers.db")
    environment: dict[str, str] = {}

    for member in bundle.members:
        for name in (
            member.credential_environment_variables
            + member.contract_reference_environment_variables
            + member.license_approval_environment_variables
            + member.certification_environment_variables
        ):
            environment[name] = f"evidence:{member.provider_identifier}:{name}"
        if member.binding_environment_variables:
            if member.provider_identifier == "eodhd-primary":
                binding = tmp_path / "eodhd.json"
                binding.write_text(
                    Path("config/eodhd_instrument_bindings.all_markets.json")
                    .read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            elif "crypto" in member.provider_identifier:
                binding = tmp_path / "crypto.json"
                binding.write_text(
                    Path("config/crypto_venue_bindings.all_markets.json")
                    .read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            else:
                binding = tmp_path / f"{member.provider_identifier}.json"
                _configured_binding(binding, member)
            for name in member.binding_environment_variables:
                environment[name] = str(binding)
        store.append(_activation(member))

    report = assess_all_market_provider_bundle(
        bundle,
        evaluated_at=AS_OF,
        environment=environment,
        provider_activation_store=store,
    )

    assert report.implementation_ready is True
    assert report.external_inputs_ready is True
    assert report.active is True
    assert report.blockers == ()
    assert all(item.ready for item in report.member_assessments)
    assert report.role_ready_counts["crypto_venue_validation"] == 2
    assert report.role_ready_counts["derivative_margin_data"] == 3


def test_bundle_cli_can_validate_repository_implementation(tmp_path: Path) -> None:
    assert bundle_main(
        [
            "--provider-activation-database",
            str(tmp_path / "providers.db"),
            "--require-implementation-ready",
        ]
    ) == 0
