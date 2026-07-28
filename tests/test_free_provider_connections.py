"""Tests for governed free-provider connection verification."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from data import ProviderError
from providers.free_connections import (
    FreeProviderConnectionIntegrityError,
    FreeProviderConnectionState,
    FreeProviderConnectionVerifier,
    SQLiteFreeProviderConnectionStore,
    load_free_provider_catalog,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class _Fred:
    def get_latest_value(self, series_id: str) -> SimpleNamespace:
        assert series_id == "DGS10"
        return SimpleNamespace(date="2026-07-27", value=4.25)


class _Sec:
    def fetch_security_master(self) -> SimpleNamespace:
        return SimpleNamespace(retrieved_at=NOW, instruments=(object(), object()))


class _Venue:
    def __init__(self, provider: str, venue: str) -> None:
        self.provider = provider
        self.venue = venue

    def fetch(self, query: object) -> SimpleNamespace:
        return SimpleNamespace(
            records=(
                SimpleNamespace(
                    instrument_id="instrument:crypto:btcusd",
                    bid=100.0,
                    ask=101.0,
                    provenance=SimpleNamespace(
                        provider=self.provider,
                        venue=self.venue,
                        observed_at=NOW,
                    ),
                ),
            )
        )


class _OpenFigi:
    def map_identifiers(self, jobs: object) -> tuple[SimpleNamespace, ...]:
        return (
            SimpleNamespace(
                matches=(SimpleNamespace(figi="BBG000B9XRY4", ticker="AAPL"),)
            ),
        )


class _Gleif:
    def fetch_lei(self, lei: str) -> SimpleNamespace:
        assert lei == "HWUPKR0MPOU8FGXBT394"
        return SimpleNamespace(
            lei=lei,
            content_hash="a" * 64,
            issuer=SimpleNamespace(issuer_id=f"GLEIF:LEI:{lei}"),
        )


def _catalog(root: Path):
    return load_free_provider_catalog(root / "config" / "free_provider_connections.json")


def _verifier(root: Path, *, environ: dict[str, str]):
    return FreeProviderConnectionVerifier(
        _catalog(root),
        environ=environ,
        repository_root=root,
        clock=lambda: NOW,
        fred_factory=lambda **kwargs: _Fred(),
        sec_factory=lambda **kwargs: _Sec(),
        coinbase_factory=lambda **kwargs: _Venue("COINBASE_EXCHANGE", "COINBASE"),
        kraken_factory=lambda **kwargs: _Venue("KRAKEN_SPOT", "KRAKEN"),
        openfigi_factory=lambda **kwargs: _OpenFigi(),
        gleif_factory=lambda **kwargs: _Gleif(),
    )


def test_catalog_contains_exact_six_supporting_services() -> None:
    root = Path(__file__).resolve().parents[1]
    catalog = _catalog(root)

    assert {item.identifier for item in catalog.providers} == {
        "fred",
        "sec_edgar",
        "coinbase_exchange",
        "kraken_spot",
        "openfigi",
        "gleif",
    }
    assert all(item.readiness_authority is False for item in catalog.providers)
    assert all(item.limitations for item in catalog.providers)


def test_all_services_connect_when_free_user_values_are_present() -> None:
    root = Path(__file__).resolve().parents[1]
    report = _verifier(
        root,
        environ={
            "FRED_API_KEY": "fred-secret",
            "SEC_USER_AGENT": "Capital Intelligence operations@example.com",
            "OPENFIGI_API_KEY": "optional-free-key",
            "CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS": str(
                root / "config" / "crypto_venue_bindings.free.json"
            ),
        },
    ).verify()

    assert report.all_enabled_connected is True
    assert report.keyless_services_connected is True
    assert report.credential_actions == ()
    assert all(
        item.state is FreeProviderConnectionState.CONNECTED
        for item in report.results
    )
    payload = report.to_dict()
    assert payload["provider_certification_granted"] is False
    assert payload["paper_test_readiness_granted"] is False
    assert payload["execution_authority_granted"] is False
    assert payload["real_money_authorized"] is False


def test_missing_free_user_values_do_not_block_keyless_services() -> None:
    root = Path(__file__).resolve().parents[1]
    report = _verifier(root, environ={}).verify()
    states = {item.provider_identifier: item.state for item in report.results}

    assert states["fred"] is FreeProviderConnectionState.CREDENTIAL_REQUIRED
    assert states["sec_edgar"] is FreeProviderConnectionState.CREDENTIAL_REQUIRED
    assert states["coinbase_exchange"] is FreeProviderConnectionState.CONNECTED
    assert states["kraken_spot"] is FreeProviderConnectionState.CONNECTED
    assert states["openfigi"] is FreeProviderConnectionState.CONNECTED
    assert states["gleif"] is FreeProviderConnectionState.CONNECTED
    assert report.keyless_services_connected is True
    assert report.all_enabled_connected is False
    assert report.credential_actions == ("FRED_API_KEY", "SEC_USER_AGENT")


def test_provider_failure_is_reported_and_secret_is_redacted() -> None:
    root = Path(__file__).resolve().parents[1]

    class _FailedFred:
        def get_latest_value(self, series_id: str) -> object:
            raise ProviderError("request failed for fred-secret")

    verifier = FreeProviderConnectionVerifier(
        _catalog(root),
        environ={
            "FRED_API_KEY": "fred-secret",
            "SEC_USER_AGENT": "Capital Intelligence operations@example.com",
        },
        repository_root=root,
        clock=lambda: NOW,
        fred_factory=lambda **kwargs: _FailedFred(),
        sec_factory=lambda **kwargs: _Sec(),
        coinbase_factory=lambda **kwargs: _Venue("COINBASE_EXCHANGE", "COINBASE"),
        kraken_factory=lambda **kwargs: _Venue("KRAKEN_SPOT", "KRAKEN"),
        openfigi_factory=lambda **kwargs: _OpenFigi(),
        gleif_factory=lambda **kwargs: _Gleif(),
    )
    result = next(
        item for item in verifier.verify().results if item.provider_identifier == "fred"
    )

    assert result.state is FreeProviderConnectionState.UNAVAILABLE
    assert "fred-secret" not in (result.error or "")
    assert "[REDACTED]" in (result.error or "")


def test_connection_history_is_idempotent_append_only_and_tamper_evident(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    report = _verifier(
        root,
        environ={
            "FRED_API_KEY": "fred-secret",
            "SEC_USER_AGENT": "Capital Intelligence operations@example.com",
        },
    ).verify()
    store = SQLiteFreeProviderConnectionStore(tmp_path / "connections.db")

    assert store.append(report) == 1
    assert store.append(report) == 1
    assert store.latest() == report
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER free_provider_connection_reports_no_update")
        connection.execute(
            "UPDATE free_provider_connection_reports SET payload_json=? WHERE sequence=1",
            (json.dumps({"tampered": True}),),
        )
    with pytest.raises(FreeProviderConnectionIntegrityError, match="content hash"):
        store.verify_integrity()
