from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import portfolio_only_runtime
import production_context_publication_governed
import production_context_publication_runtime
from operations import capability_scoped_discovery
from operations.free_paper_pilot import load_free_paper_pilot_universe
from portfolio.initialization import ensure_canonical_portfolio_store
from portfolio.state import SQLiteCanonicalPortfolioStore


AS_OF = datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc)


def test_render_context_uses_capability_scoped_discovery_without_global_gate(monkeypatch):
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
        equity_discovery_probe=lambda *_args, **_kwargs: object(),
        clock=lambda: AS_OF,
    )

    assert captured["comprehensive_discovery_required"] is False
    probe = captured["comprehensive_discovery_probe"]
    assert callable(probe)
    assert probe.__name__ == "discover_currently_certified_capabilities"


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


def test_capability_carry_forward_intersects_exact_current_evidence(monkeypatch):
    universe = load_free_paper_pilot_universe()
    qualified = replace(
        universe,
        identifier="active-publication:test",
        instruments=universe.instruments[:3],
    )
    contracts = capability_scoped_discovery._instrument_contracts(qualified)
    first, second, third = qualified.instruments

    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_publication_source",
        lambda: (Path("active-paper-universe.json"), "eligible:test"),
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "load_active_paper_universe_for_publication",
        lambda *_args, **_kwargs: qualified,
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_evidence_contracts",
        lambda _as_of: {
            second.instrument_identifier: contracts[second.instrument_identifier],
        },
    )

    result = capability_scoped_discovery.discover_currently_certified_capabilities(
        as_of=AS_OF,
        excluded_symbols=(first.symbol,),
    )

    assert result.instruments == (second,)
    assert third not in result.instruments
    assert result.scope_state == "capability_scoped"
    assert "exact current signed evidence coverage" in result.limitations[0]


def test_missing_global_evidence_blocks_only_dynamic_carry_forward(monkeypatch):
    universe = load_free_paper_pilot_universe()
    qualified = replace(universe, instruments=universe.instruments[:2])

    monkeypatch.setattr(
        capability_scoped_discovery,
        "_current_publication_source",
        lambda: (Path("active-paper-universe.json"), "eligible:test"),
    )
    monkeypatch.setattr(
        capability_scoped_discovery,
        "load_active_paper_universe_for_publication",
        lambda *_args, **_kwargs: qualified,
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
    assert "without blocking independently qualified bootstrap" in result.limitations[0]


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
    ) == -0.1
