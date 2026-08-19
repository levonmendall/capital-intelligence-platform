from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import portfolio_only_runtime
import production_context_publication_governed
import production_context_publication_runtime
from cio import CandidateAssetClass
from operations import capability_scoped_discovery
from operations.free_paper_pilot import load_free_paper_pilot_universe
from portfolio.initialization import ensure_canonical_portfolio_store
from portfolio.state import SQLiteCanonicalPortfolioStore


AS_OF = datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc)


def _dynamic(template, *, suffix: str, symbol: str):
    return replace(
        template,
        symbol=symbol,
        instrument_identifier=f"{template.instrument_identifier}:{suffix}",
        name=f"Dynamic {suffix}",
    )


def test_render_context_uses_capability_scoped_candidates_without_global_gate(monkeypatch):
    captured: dict[str, object] = {}

    def fake_prepare(**kwargs):
        captured.update(kwargs)
        return production_context_publication_runtime.ProductionContextPublicationResult(
            state="blocked",
            cycle_key="canonical-cio:test",
            scheduled_for=AS_OF,
            decision_as_of=AS_OF,
            detail="test boundary",
        )

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION", raising=False)
    monkeypatch.setattr(
        production_context_publication_governed,
        "prepare_governed_production_context_for_cycle",
        fake_prepare,
    )

    production_context_publication_runtime.prepare_production_context_for_cycle(
        settings=SimpleNamespace(),
        scheduled_for=AS_OF,
        readiness_probe=lambda _universe: object(),
        cash_probe=lambda: object(),
        evidence_probe=lambda *_args, **_kwargs: {},
        clock=lambda: AS_OF,
    )

    assert captured["comprehensive_discovery_required"] is False
    global_probe = captured["comprehensive_discovery_probe"]
    equity_probe = captured["equity_discovery_probe"]
    assert callable(global_probe)
    assert callable(equity_probe)
    assert global_probe.__name__ == "discover_currently_certified_capabilities"
    assert equity_probe.__name__ == "discover_currently_certified_us_equities"


def test_local_context_keeps_full_discovery_behavior_unless_opted_in(monkeypatch):
    captured: dict[str, object] = {}

    def fake_prepare(**kwargs):
        captured.update(kwargs)
        return production_context_publication_runtime.ProductionContextPublicationResult(
            state="blocked",
            cycle_key="canonical-cio:test",
            scheduled_for=AS_OF,
            decision_as_of=AS_OF,
            detail="test boundary",
        )

    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION", raising=False)
    monkeypatch.setattr(
        production_context_publication_governed,
        "prepare_governed_production_context_for_cycle",
        fake_prepare,
    )

    production_context_publication_runtime.prepare_production_context_for_cycle(
        settings=SimpleNamespace(),
        scheduled_for=AS_OF,
        readiness_probe=lambda _universe: object(),
        cash_probe=lambda: object(),
        evidence_probe=lambda *_args, **_kwargs: {},
        equity_discovery_probe=lambda *_args, **_kwargs: object(),
        clock=lambda: AS_OF,
    )

    assert captured["comprehensive_discovery_probe"] is None
    assert captured["comprehensive_discovery_required"] is None


def test_capability_candidates_intersect_exact_operating_evidence(monkeypatch):
    base = load_free_paper_pilot_universe()
    dynamic_a = _dynamic(base.instruments[0], suffix="a", symbol="DYNA")
    dynamic_b = _dynamic(base.instruments[1], suffix="b", symbol="DYNB")
    dynamic_c = _dynamic(base.instruments[2], suffix="c", symbol="DYNC")
    authorized = replace(
        base,
        identifier="active-publication:test",
        instruments=(*base.instruments, dynamic_a, dynamic_b, dynamic_c),
    )
    contracts = capability_scoped_discovery._instrument_contracts(authorized)

    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_publication_identifier",
        lambda: "eligible:test",
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "load_current_authorized_universe",
        lambda **_kwargs: authorized,
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_evidence_contracts",
        lambda _as_of: {
            dynamic_b.instrument_identifier: contracts[dynamic_b.instrument_identifier],
        },
    )

    result = capability_scoped_discovery.discover_currently_certified_capabilities(
        as_of=AS_OF,
        excluded_symbols=tuple(item.symbol for item in base.instruments) + (dynamic_a.symbol,),
    )

    assert result.instruments == (dynamic_b,)
    assert result.selected == (dynamic_b,)
    assert result.screened_asset_count == 2
    assert result.snapshot_covered_count == 1
    assert dynamic_c not in result.instruments
    assert result.scope_state == "capability_scoped"
    assert "fresh independent operating-evidence snapshot" in result.limitations[0]


def test_missing_operating_evidence_blocks_only_dynamic_candidates(monkeypatch):
    base = load_free_paper_pilot_universe()
    dynamic = _dynamic(base.instruments[0], suffix="optional", symbol="DYNX")
    authorized = replace(base, instruments=(*base.instruments, dynamic))

    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_publication_identifier",
        lambda: "eligible:test",
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "load_current_authorized_universe",
        lambda **_kwargs: authorized,
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_evidence_contracts",
        lambda _as_of: None,
    )

    result = capability_scoped_discovery.discover_currently_certified_capabilities(
        as_of=AS_OF,
    )

    assert result.instruments == ()
    assert result.selected == ()
    assert result.screened_asset_count == len(authorized.instruments)
    assert result.snapshot_covered_count == 0
    assert "dynamic candidates are withheld" in result.limitations[0]


def test_us_equity_view_filters_by_canonical_asset_class(monkeypatch):
    base = load_free_paper_pilot_universe()
    stock = replace(
        base.instruments[0],
        symbol="ACME",
        instrument_identifier="instrument:us-equity:acme",
        name="Acme Corporation",
        execution_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure="us_equity",
        instrument_type="common_stock",
        maximum_weight=0.01,
        issuer_cik="0000000001",
    )
    authorized = replace(
        base,
        identifier="authorized:test",
        instruments=(*base.instruments, stock),
    )
    contracts = capability_scoped_discovery._instrument_contracts(authorized)

    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_publication_identifier",
        lambda: "eligible:test",
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "load_current_authorized_universe",
        lambda **_kwargs: authorized,
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_evidence_contracts",
        lambda _as_of: contracts,
    )

    result = capability_scoped_discovery.discover_currently_certified_us_equities(
        as_of=AS_OF,
        excluded_symbols=tuple(item.symbol for item in base.instruments),
    )

    assert result.instruments == (stock,)
    assert result.selected == (stock,)
    assert result.screened_asset_count == 1
    assert result.snapshot_covered_count == 1
    assert result.instruments[0].instrument_type == "common_stock"


def test_capability_discovery_publication_metadata_is_self_consistent():
    result = capability_scoped_discovery.CapabilityScopedDiscoveryResult(
        as_of=AS_OF,
        instruments=(object(),),
        source_publication_identifier="eligible:test",
        limitations=(),
        screened_asset_count=2,
        snapshot_covered_count=1,
    )

    assert result.selected == result.instruments
    with pytest.raises(ValueError, match="snapshot_covered_count"):
        capability_scoped_discovery.CapabilityScopedDiscoveryResult(
            as_of=AS_OF,
            instruments=(object(),),
            source_publication_identifier="eligible:test",
            limitations=(),
            screened_asset_count=1,
            snapshot_covered_count=0,
        )


def test_render_reset_epoch_archives_once_and_starts_fresh_250k(monkeypatch, tmp_path):
    path = tmp_path / "canonical.db"

    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_PORTFOLIO_RESET_EPOCH", raising=False)
    original = ensure_canonical_portfolio_store(path, as_of=AS_OF)
    assert original.created is True
    assert original.reset is False

    monkeypatch.setenv("RENDER", "true")
    reset = ensure_canonical_portfolio_store(path, as_of=AS_OF + timedelta(minutes=1))
    assert reset.created is True
    assert reset.reset is True
    assert reset.archive_path is not None
    assert reset.archive_path.exists()

    store = SQLiteCanonicalPortfolioStore(path)
    store.verify_integrity()
    latest = store.latest("COMPOUNDING")
    assert latest is not None
    assert latest.starting_capital == 250000.0
    assert latest.cash_amount == 250000.0
    assert latest.nav == 250000.0
    assert latest.positions == ()
    assert "explicit-paper-reset:capability-runtime-v2-2026-08-19" in latest.source_identifiers

    recovered = ensure_canonical_portfolio_store(
        path,
        as_of=AS_OF + timedelta(minutes=2),
    )
    assert recovered.created is False
    assert recovered.reset is False
    assert recovered.state_generation_id == latest.identifier


def test_explicit_reset_epoch_can_be_overridden_for_future_governed_resets(monkeypatch, tmp_path):
    path = tmp_path / "canonical.db"
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_PORTFOLIO_RESET_EPOCH", raising=False)
    ensure_canonical_portfolio_store(path, as_of=AS_OF)

    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PORTFOLIO_RESET_EPOCH", "test-epoch")
    reset = ensure_canonical_portfolio_store(path, as_of=AS_OF + timedelta(minutes=1))
    assert reset.reset is True
    latest = SQLiteCanonicalPortfolioStore(path).latest("COMPOUNDING")
    assert latest is not None
    assert latest.identifier.endswith(":test-epoch")


def test_portfolio_only_presentation_defaults_on_render(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_PORTFOLIO_ONLY_UI", raising=False)
    assert portfolio_only_runtime.portfolio_only_enabled() is True
    assert portfolio_only_runtime._deployed(250000.0, 250000.0) == 0.0
    assert portfolio_only_runtime._drawdown(
        [
            {"created_at": "1", "nav": 250000.0},
            {"created_at": "2", "nav": 275000.0},
            {"created_at": "3", "nav": 247500.0},
        ]
    ) == pytest.approx(-0.1)
