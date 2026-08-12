from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.data_readiness_core import DataDomain
from governance.market_data_bundle import load_all_market_provider_bundle
from governance.provider_activation import ProviderActivation, SQLiteProviderActivationStore
from run_provider_activation_package import main

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _domains_for_member(member) -> tuple[DataDomain, ...]:
    dataset_domain_overrides = {
        "market_history": DataDomain.MARKET_PRICES,
    }
    domains = tuple(
        dataset_domain_overrides[item.value]
        if item.value in dataset_domain_overrides
        else DataDomain(item.value)
        for item in member.required_dataset_types
    )
    return tuple(dict.fromkeys(domains))


def test_complete_activation_package_is_appended_with_integrity(tmp_path: Path) -> None:
    bundle = load_all_market_provider_bundle("config/all_market_provider_bundle.json")
    directory = tmp_path / "activations"
    directory.mkdir()
    for member in bundle.members:
        domains = _domains_for_member(member)
        activation = ProviderActivation(
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
            rationale="Complete reviewed provider package fixture.",
            approved_at=AS_OF - timedelta(days=2),
            effective_at=AS_OF - timedelta(days=1),
            expires_at=AS_OF + timedelta(days=30),
            source_identifiers=(f"contract:{member.provider_identifier}:test",),
        )
        (directory / f"{member.provider_identifier}.json").write_text(
            json.dumps(activation.to_dict()), encoding="utf-8"
        )
    database = tmp_path / "providers.db"

    assert main([
        "--activation-directory", str(directory),
        "--database", str(database),
        "--evaluated-at", AS_OF.isoformat(),
    ]) == 0

    store = SQLiteProviderActivationStore(database)
    store.verify_integrity()
    assert len(store.activations()) == len(bundle.members)


def test_disabled_example_package_cannot_be_appended(tmp_path: Path) -> None:
    assert main([
        "--activation-directory", "config/provider_activations/all_markets",
        "--database", str(tmp_path / "providers.db"),
        "--evaluated-at", AS_OF.isoformat(),
    ]) == 3
