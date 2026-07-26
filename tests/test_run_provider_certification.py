"""CLI tests for provider certification execution and persistence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from data import (
    AssetClass,
    IdentifierAssignment,
    IdentifierScheme,
    Instrument,
    InstrumentIdentifier,
    InstrumentRecord,
    InstrumentType,
    Issuer,
    IssuerRecord,
    ListingRecord,
    ListingStatus,
    SecurityEntityType,
    SecurityMasterCatalog,
    SecurityMasterCatalogDelivery,
    SecurityMasterCoverage,
    TradingCalendar,
)
import run_provider_certification

UTC = timezone.utc
NOW = datetime(2026, 7, 26, 18, tzinfo=UTC)


class Provider:
    name = "LICENSED_A"

    def __init__(self) -> None:
        issuer = Issuer(
            issuer_id="issuer:acme",
            name="Acme Corporation",
            identifiers=(
                InstrumentIdentifier(IdentifierScheme.CIK, "1234567", provider=self.name),
            ),
        )
        instrument = Instrument(
            instrument_id="instrument:acme",
            name="Acme Common",
            asset_class=AssetClass.EQUITY,
            instrument_type=InstrumentType.COMMON_STOCK,
            issuer_id=issuer.issuer_id,
            identifiers=(
                InstrumentIdentifier(IdentifierScheme.FIGI, "BBG000000001", provider=self.name),
            ),
        )
        start = datetime(2020, 1, 2, tzinfo=UTC)
        self.catalog = SecurityMasterCatalog(
            identifier="catalog:licensed-a",
            version="security-master.v1",
            coverage=SecurityMasterCoverage(
                source=self.name,
                source_version="licensed-a.v1",
                licensed=True,
                complete_universe=True,
                point_in_time=True,
                historical_identifiers=True,
                listing_history=True,
                delistings=True,
                corporate_actions=True,
                provenance_complete=True,
                service_level_defined=True,
            ),
            issuers=(IssuerRecord("issuer-record", issuer, start, None, start, "source:issuer"),),
            instruments=(InstrumentRecord("instrument-record", instrument, start, None, start, "source:instrument"),),
            identifiers=(
                IdentifierAssignment(
                    "identifier-record",
                    "assignment:figi",
                    SecurityEntityType.INSTRUMENT,
                    instrument.instrument_id,
                    instrument.identifiers[0],
                    start,
                    None,
                    start,
                    "source:identifier",
                ),
            ),
            listings=(
                ListingRecord(
                    "listing-record",
                    "listing:acme",
                    instrument.instrument_id,
                    "NASDAQ",
                    "ACME",
                    "US",
                    TradingCalendar.EXCHANGE,
                    ListingStatus.ACTIVE,
                    True,
                    start,
                    None,
                    start,
                    "source:listing",
                ),
            ),
            actions=(),
        )

    def fetch_security_master_delivery(self, query):
        return SecurityMasterCatalogDelivery(
            catalog=self.catalog,
            observed_at=query.requested_at - timedelta(hours=1),
            retrieved_at=query.requested_at,
            request_identifier=query.identifier,
        )


def manifest(*, licensed: bool = True) -> dict[str, object]:
    return {
        "provider": "LICENSED_A",
        "product": "Global Security Master",
        "manifest_version": "manifest.v1",
        "source_version": "licensed-a.v1",
        "license_reference": "contract-001",
        "license_verified": licensed,
        "complete_eligible_universe": True,
        "point_in_time_delivery": True,
        "historical_identifiers": True,
        "listing_and_venue_history": True,
        "delisted_securities": True,
        "corporate_actions": True,
        "revision_history": True,
        "provenance_complete": True,
        "cross_venue_adjustment_policy": "Venue-specific history with effective primary listing.",
        "service_level_reference": "sla-001",
        "maximum_delivery_age_hours": 24,
        "valid_from": (NOW - timedelta(days=1)).isoformat(),
        "valid_until": (NOW + timedelta(days=365)).isoformat(),
    }


def suite() -> list[dict[str, object]]:
    return [
        {
            "identifier": "current-identity",
            "kind": "current_identity",
            "description": "Current symbol and listing are available.",
            "query": {
                "identifier": "current-identity",
                "as_of": NOW.isoformat(),
                "knowledge_cutoff": NOW.isoformat(),
                "requested_at": NOW.isoformat(),
            },
            "expected_symbols": ["ACME"],
            "expected_listings": [
                {"symbol": "ACME", "venue": "NASDAQ", "status": "active"}
            ],
            "minimum_instrument_count": 1,
        }
    ]


def write_json(path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_cli_approves_and_persists_provider(tmp_path, monkeypatch, capsys) -> None:
    manifest_path = tmp_path / "manifest.json"
    suite_path = tmp_path / "suite.json"
    database_path = tmp_path / "security-master.db"
    write_json(manifest_path, manifest())
    write_json(suite_path, suite())
    monkeypatch.setattr(run_provider_certification, "_provider", lambda _: Provider())

    result = run_provider_certification.main(
        [
            "--provider-factory", "ignored:factory",
            "--manifest", str(manifest_path),
            "--suite", str(suite_path),
            "--database", str(database_path),
            "--identifier", "certification:approved",
            "--certified-at", NOW.isoformat(),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["decision"] == "approved"
    assert payload["registry_sequence"] == 1
    assert len(payload["content_hash"]) == 64


def test_cli_returns_rejected_for_unverified_license(tmp_path, monkeypatch, capsys) -> None:
    manifest_path = tmp_path / "manifest.json"
    suite_path = tmp_path / "suite.json"
    write_json(manifest_path, manifest(licensed=False))
    write_json(suite_path, suite())
    monkeypatch.setattr(run_provider_certification, "_provider", lambda _: Provider())

    result = run_provider_certification.main(
        [
            "--provider-factory", "ignored:factory",
            "--manifest", str(manifest_path),
            "--suite", str(suite_path),
            "--database", str(tmp_path / "security-master.db"),
            "--certified-at", NOW.isoformat(),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 3
    assert payload["decision"] == "rejected"
    assert "commercial license is not verified" in payload["manifest_deficiencies"]
