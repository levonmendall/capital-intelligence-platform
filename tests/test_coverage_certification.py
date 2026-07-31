from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance.coverage_certification import (
    HistoricalCertificationBoundary,
    HistoricalCertificationDomain,
    HistoricalCertificationState,
    HistoricalEvidenceReference,
    SQLiteCoverageCertificationStore,
    certify_historical_cutoff,
    load_historical_boundaries,
    load_market_coverage,
)
from api.routes.governance import historical_certification, market_coverage


ROOT = Path(__file__).resolve().parents[1]
MARKETS = ROOT / "config" / "market_coverage_registry.v1.json"
HISTORY = ROOT / "config" / "historical_certification_boundaries.v1.json"
NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)


def test_monitored_certified_and_allocatable_scopes_are_distinct() -> None:
    registry = load_market_coverage(MARKETS)
    direct_crypto = next(item for item in registry.markets if item.market == "direct_spot_crypto")
    pilot = next(item for item in registry.markets if item.market == "us_listed_pilot_wrappers")
    assert direct_crypto.monitored and not direct_crypto.decision_certified
    assert direct_crypto.allocatable_instrument_identifiers == ()
    assert pilot.decision_certified
    assert len(pilot.allocatable_instrument_identifiers) == 15
    registry.require_allocatable(market="us_listed_pilot_wrappers", instrument_identifier="instrument:us-etf:ibit")
    with pytest.raises(ValueError, match="not currently allocatable"):
        registry.require_allocatable(market="direct_spot_crypto", instrument_identifier="instrument:crypto:btc")
    assert registry.to_dict()["real_money_authorized"] is False


def test_baseline_names_every_required_historical_domain_and_fails_closed() -> None:
    boundaries = load_historical_boundaries(HISTORY)
    assert {item.domain for item in boundaries} == set(HistoricalCertificationDomain)
    report = certify_historical_cutoff(cutoff=NOW, boundaries=boundaries, evidence=())
    assert not report.ready
    assert len(report.blockers) == len(HistoricalCertificationDomain)
    assert report.to_dict()["research_only"]
    assert not report.to_dict()["performance_claims_authorized"]


def _certified(domain, provider="provider:test", *, start=NOW - timedelta(days=3650)):
    return HistoricalCertificationBoundary(
        domain=domain,
        state=HistoricalCertificationState.CERTIFIED,
        provider_identifier=provider,
        coverage_start=start,
        coverage_end=None,
        certification_identifier=f"cert:{domain.value}",
        evidence_identifiers=(f"evidence:{domain.value}",),
        revision_safe=True,
        survivorship_safe=True,
        limitation=None,
    )


@pytest.mark.parametrize(
    "domain",
    (
        HistoricalCertificationDomain.MACRO_VINTAGES,
        HistoricalCertificationDomain.FILINGS_REVISIONS,
        HistoricalCertificationDomain.LISTINGS_DELISTINGS,
        HistoricalCertificationDomain.CORPORATE_ACTIONS,
        HistoricalCertificationDomain.INDEX_MEMBERSHIP,
        HistoricalCertificationDomain.LIQUIDITY_QUOTES,
        HistoricalCertificationDomain.MARKET_CALENDARS,
        HistoricalCertificationDomain.PROVIDER_AVAILABILITY,
    ),
)
def test_each_certified_domain_is_required_at_the_cutoff(domain) -> None:
    boundary = _certified(domain)
    report = certify_historical_cutoff(
        cutoff=NOW,
        boundaries=(boundary,),
        evidence=(),
        required_domains=(domain,),
    )
    assert report.ready


def test_future_revision_and_provider_before_availability_are_rejected() -> None:
    domain = HistoricalCertificationDomain.FILINGS_REVISIONS
    future = HistoricalEvidenceReference(
        identifier="filing:restatement",
        domain=domain,
        provider_identifier="provider:test",
        observed_at=NOW,
        available_at=NOW + timedelta(days=10),
        supersedes_identifier="filing:original",
    )
    report = certify_historical_cutoff(
        cutoff=NOW,
        boundaries=(_certified(domain),),
        evidence=(future,),
        required_domains=(domain,),
    )
    assert not report.ready
    assert any("future-known" in item for item in report.blockers)

    later_provider = _certified(domain, start=NOW + timedelta(days=1))
    unavailable = certify_historical_cutoff(
        cutoff=NOW,
        boundaries=(later_provider,),
        evidence=(),
        required_domains=(domain,),
    )
    assert not unavailable.ready


def test_revision_and_survivorship_domains_cannot_be_weakly_certified() -> None:
    with pytest.raises(ValueError, match="revision safe"):
        HistoricalCertificationBoundary(
            domain=HistoricalCertificationDomain.MACRO_VINTAGES,
            state=HistoricalCertificationState.CERTIFIED,
            provider_identifier="provider",
            coverage_start=NOW - timedelta(days=1),
            coverage_end=None,
            certification_identifier="cert",
            evidence_identifiers=("evidence",),
            revision_safe=False,
            survivorship_safe=True,
            limitation=None,
        )
    with pytest.raises(ValueError, match="survivorship safe"):
        HistoricalCertificationBoundary(
            domain=HistoricalCertificationDomain.INDEX_MEMBERSHIP,
            state=HistoricalCertificationState.CERTIFIED,
            provider_identifier="provider",
            coverage_start=NOW - timedelta(days=1),
            coverage_end=None,
            certification_identifier="cert",
            evidence_identifiers=("evidence",),
            revision_safe=True,
            survivorship_safe=False,
            limitation=None,
        )


def test_coverage_store_is_append_only(tmp_path) -> None:
    registry = load_market_coverage(MARKETS)
    store = SQLiteCoverageCertificationStore(tmp_path / "coverage.db")
    store.append(identifier=registry.identifier, recorded_at=NOW, payload=registry.to_dict())
    store.append(identifier=registry.identifier, recorded_at=NOW, payload=registry.to_dict())
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM coverage_certifications").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE coverage_certifications SET payload_json='{}'")


def test_configs_cannot_authorize_performance_or_real_money() -> None:
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    markets = json.loads(MARKETS.read_text(encoding="utf-8"))
    assert history["research_only"] is True
    assert history["performance_claims_authorized"] is False
    assert history["policy_promotion_authorized"] is False
    assert history["real_money_authorized"] is False
    assert markets["real_money_authorized"] is False


def test_read_only_api_presentations_keep_scopes_and_blockers_visible(monkeypatch) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_MARKET_COVERAGE_REGISTRY", str(MARKETS))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_HISTORICAL_CERTIFICATION_BOUNDARIES", str(HISTORY))
    market_payload = market_coverage()
    history_payload = historical_certification()
    assert any(item["monitored"] and not item["decision_certified"] for item in market_payload["markets"])
    assert not history_payload["ready"]
    assert len(history_payload["blockers"]) == 8
    assert history_payload["real_money_authorized"] is False
