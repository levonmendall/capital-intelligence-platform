from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import production_context_publication_runtime as runtime
from operations import qualified_equity_discovery, qualified_paper_evidence


def _install_governed(monkeypatch, observed):
    result = runtime.ProductionContextPublicationResult(
        state="blocked",
        cycle_key="canonical-cio:test",
        scheduled_for=datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc),
        decision_as_of=None,
        detail="fixture only: verify provider-free probe selection",
    )

    def governed(**kwargs):
        observed.update(kwargs)
        return result

    monkeypatch.setitem(
        sys.modules,
        "production_context_publication_governed",
        SimpleNamespace(prepare_governed_production_context_for_cycle=governed),
    )
    return result


def test_runtime_defaults_to_qualified_equity_discovery(monkeypatch, tmp_path) -> None:
    scheduled = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    observed: dict[str, object] = {}
    expected = _install_governed(monkeypatch, observed)
    monkeypatch.setattr(
        qualified_paper_evidence,
        "production_snapshot_probe_enabled",
        lambda values=None: False,
    )

    actual = runtime.prepare_production_context_for_cycle(
        settings=SimpleNamespace(scheduler_timezone="America/Los_Angeles"),
        scheduled_for=scheduled,
        universe_path=tmp_path / "universe.json",
    )

    assert actual is expected
    assert observed["equity_discovery_probe"] is qualified_equity_discovery.discover_us_equities
    assert observed["evidence_probe"] is None


def test_production_runtime_defaults_to_qualified_paper_evidence(monkeypatch, tmp_path) -> None:
    scheduled = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    observed: dict[str, object] = {}
    _install_governed(monkeypatch, observed)
    monkeypatch.setattr(
        qualified_paper_evidence,
        "production_snapshot_probe_enabled",
        lambda values=None: True,
    )

    runtime.prepare_production_context_for_cycle(
        settings=SimpleNamespace(scheduler_timezone="America/Los_Angeles"),
        scheduled_for=scheduled,
        universe_path=tmp_path / "universe.json",
    )

    assert observed["equity_discovery_probe"] is qualified_equity_discovery.discover_us_equities
    assert observed["evidence_probe"] is qualified_paper_evidence.qualified_paper_evidence_probe


def test_runtime_preserves_explicit_provider_probes(monkeypatch, tmp_path) -> None:
    scheduled = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    observed: dict[str, object] = {}
    _install_governed(monkeypatch, observed)
    monkeypatch.setattr(
        qualified_paper_evidence,
        "production_snapshot_probe_enabled",
        lambda values=None: True,
    )

    def explicit_equity(**kwargs):
        return kwargs

    def explicit_evidence(*args, **kwargs):
        return args, kwargs

    runtime.prepare_production_context_for_cycle(
        settings=SimpleNamespace(scheduler_timezone="America/Los_Angeles"),
        scheduled_for=scheduled,
        universe_path=tmp_path / "universe.json",
        equity_discovery_probe=explicit_equity,
        evidence_probe=explicit_evidence,
    )

    assert observed["equity_discovery_probe"] is explicit_equity
    assert observed["evidence_probe"] is explicit_evidence
