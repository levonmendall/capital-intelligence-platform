from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import production_context_publication_runtime as runtime
from operations import qualified_equity_discovery


def test_runtime_defaults_to_qualified_equity_discovery(monkeypatch, tmp_path) -> None:
    scheduled = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    observed: dict[str, object] = {}

    def governed(**kwargs):
        observed.update(kwargs)
        return "context-result"

    fake_governed = SimpleNamespace(
        prepare_governed_production_context_for_cycle=governed
    )
    monkeypatch.setitem(sys.modules, "production_context_publication_governed", fake_governed)

    settings = SimpleNamespace(scheduler_timezone="America/Los_Angeles")
    actual = runtime.prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled,
        universe_path=tmp_path / "universe.json",
    )

    assert actual == "context-result"
    assert observed["equity_discovery_probe"] is qualified_equity_discovery.discover_us_equities


def test_runtime_preserves_explicit_equity_probe(monkeypatch, tmp_path) -> None:
    scheduled = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    observed: dict[str, object] = {}

    def governed(**kwargs):
        observed.update(kwargs)
        return "context-result"

    def explicit_probe(**kwargs):
        return kwargs

    monkeypatch.setitem(
        sys.modules,
        "production_context_publication_governed",
        SimpleNamespace(prepare_governed_production_context_for_cycle=governed),
    )

    runtime.prepare_production_context_for_cycle(
        settings=SimpleNamespace(scheduler_timezone="America/Los_Angeles"),
        scheduled_for=scheduled,
        universe_path=tmp_path / "universe.json",
        equity_discovery_probe=explicit_probe,
    )

    assert observed["equity_discovery_probe"] is explicit_probe
