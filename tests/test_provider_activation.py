from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance import load_data_readiness_manifest
from governance.data_readiness import DataDomain
from governance.provider_activation import (
    ProviderActivation,
    ProviderActivationAuthority,
    ProviderActivationError,
    SQLiteProviderActivationStore,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 2, 0, tzinfo=UTC)


def _activation(provider, *, identifier: str = "activation:global-market:v1", domains=None):
    return ProviderActivation(
        identifier=identifier,
        provider_identifier=provider.identifier,
        provider_name="Certified Global Market Data",
        enabled=True,
        approved_domains=tuple(provider.domains if domains is None else domains),
        authoritative_domains=provider.authoritative_domains,
        usage_rights_approved=True,
        point_in_time_supported=True,
        historical_coverage_supported=True,
        provenance_complete=True,
        service_level_defined=True,
        storage_and_backup_approved=True,
        derived_analytics_approved=True,
        paper_simulation_approved=True,
        certification_identifier="certification:global-market:v1",
        approved_by="data-governance-committee",
        rationale="Licensed and certified for controlled paper simulation.",
        approved_at=AS_OF - timedelta(days=2),
        effective_at=AS_OF - timedelta(days=1),
        expires_at=AS_OF + timedelta(days=30),
        source_identifiers=("contract:global-market:v1", "suite:global-market:v1"),
    )


def test_active_provider_activation_overlays_fail_closed_manifest(tmp_path: Path) -> None:
    manifest = load_data_readiness_manifest("config/all_markets_data_readiness.json")
    provider = next(
        item for item in manifest.providers
        if item.identifier == "commercial-global-market-data"
    )
    store = SQLiteProviderActivationStore(tmp_path / "providers.db")
    sequence = store.append(_activation(provider))

    overlay = ProviderActivationAuthority(store).overlay(
        manifest,
        evaluated_at=AS_OF,
    )
    activated = next(
        item for item in overlay.manifest.providers
        if item.identifier == provider.identifier
    )

    assert sequence == 1
    assert activated.enabled is True
    assert activated.provider_name == "Certified Global Market Data"
    assert activated.certification_identifier == "certification:global-market:v1"
    assert overlay.activation_identifiers == ("activation:global-market:v1",)
    assert provider.identifier not in overlay.inactive_provider_identifiers
    store.verify_integrity()


def test_expired_activation_does_not_mutate_source_policy(tmp_path: Path) -> None:
    manifest = load_data_readiness_manifest("config/all_markets_data_readiness.json")
    provider = next(
        item for item in manifest.providers
        if item.identifier == "commercial-global-market-data"
    )
    store = SQLiteProviderActivationStore(tmp_path / "providers.db")
    store.append(_activation(provider))

    overlay = ProviderActivationAuthority(store).overlay(
        manifest,
        evaluated_at=AS_OF + timedelta(days=31),
    )
    current = next(
        item for item in overlay.manifest.providers
        if item.identifier == provider.identifier
    )

    assert current == provider
    assert overlay.activation_identifiers == ()
    assert provider.identifier in overlay.inactive_provider_identifiers


def test_activation_cannot_expand_manifest_authority(tmp_path: Path) -> None:
    manifest = load_data_readiness_manifest("config/all_markets_data_readiness.json")
    provider = next(
        item for item in manifest.providers
        if item.identifier == "commercial-global-market-data"
    )
    store = SQLiteProviderActivationStore(tmp_path / "providers.db")
    store.append(
        _activation(
            provider,
            domains=(*provider.domains, DataDomain.FILINGS),
        )
    )

    with pytest.raises(ProviderActivationError, match="undeclared domains"):
        ProviderActivationAuthority(store).overlay(manifest, evaluated_at=AS_OF)


def test_enabled_activation_requires_every_operating_approval() -> None:
    manifest = load_data_readiness_manifest("config/all_markets_data_readiness.json")
    provider = next(
        item for item in manifest.providers
        if item.identifier == "commercial-global-market-data"
    )
    payload = _activation(provider).to_dict()
    payload["paper_simulation_approved"] = False

    with pytest.raises(ValueError, match="incomplete"):
        ProviderActivation.from_dict(payload)


def test_activation_json_rejects_string_booleans() -> None:
    manifest = load_data_readiness_manifest("config/all_markets_data_readiness.json")
    provider = next(
        item for item in manifest.providers
        if item.identifier == "commercial-global-market-data"
    )
    payload = _activation(provider).to_dict()
    payload["enabled"] = "true"

    with pytest.raises(TypeError, match="enabled must be a bool"):
        ProviderActivation.from_dict(payload)
