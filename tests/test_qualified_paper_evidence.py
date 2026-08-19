from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from operations import qualified_paper_evidence as qualified
from operations.free_paper_pilot import load_free_paper_pilot_universe


def _production(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", "true")


def test_production_probe_verifies_source_snapshot_then_projects_exact_subset(
    monkeypatch, tmp_path
) -> None:
    as_of = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)
    observed: dict[str, object] = {}
    source = load_free_paper_pilot_universe()
    requested = replace(
        source,
        identifier="capability-authorized:test",
        instruments=source.instruments[:2],
        limitations=(*source.limitations, "capability-scoped test subset"),
    )
    source_symbols = tuple(item.symbol for item in source.instruments[:3])
    payload = {
        "bars": {symbol: (symbol, "bars") for symbol in source_symbols},
        "quotes": {symbol: (symbol, "quote") for symbol in source_symbols},
        "company_facts": {symbol: {"symbol": symbol} for symbol in source_symbols},
        "_direct_market_errors": {symbol: "none" for symbol in source_symbols},
        "_scheduled_closed_symbols": source_symbols,
        "macro": {"DGS10": {"date": "2026-08-15", "value": 4.0}},
        "provider_clock": {},
    }

    _production(monkeypatch, tmp_path)

    def ensure(**kwargs):
        observed["ensure"] = kwargs
        return SimpleNamespace(plane_as_of=as_of)

    def scope(**kwargs):
        observed["scope"] = kwargs
        return SimpleNamespace(held_symbols=(), tracked_symbols=())

    def build(**kwargs):
        observed["build"] = kwargs
        return source, ()

    def load(**kwargs):
        observed["load"] = kwargs
        return SimpleNamespace(snapshot_id="paper-snapshot-test", payload=payload)

    monkeypatch.setattr(qualified, "ensure_point_in_time_snapshot", ensure)
    monkeypatch.setattr(qualified, "load_evidence_state_scope", scope)
    monkeypatch.setattr(qualified, "build_evidence_collection_universe", build)
    monkeypatch.setattr(qualified, "load_paper_evidence_snapshot", load)

    actual = qualified.qualified_paper_evidence_probe(requested, as_of)

    expected_symbols = {item.symbol for item in requested.instruments}
    assert set(actual["bars"]) == expected_symbols
    assert set(actual["quotes"]) == expected_symbols
    assert set(actual["company_facts"]) == expected_symbols
    assert set(actual["_direct_market_errors"]) == expected_symbols
    assert set(actual["_scheduled_closed_symbols"]) == expected_symbols
    assert actual["macro"] is payload["macro"]
    assert observed["ensure"]["allow_refresh"] is False
    assert observed["ensure"]["cutoff"] == as_of
    assert observed["load"]["evidence_as_of"] == as_of
    assert observed["load"]["universe"] is source
    projection = actual["_paper_evidence_projection"]
    assert projection["source_snapshot_id"] == "paper-snapshot-test"
    assert projection["source_instrument_count"] == len(source.instruments)
    assert projection["requested_instrument_count"] == len(requested.instruments)
    assert projection["exact_structural_subset"] is True
    assert projection["provider_refresh_permitted"] is False
    assert qualified.os.environ[
        "CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"
    ] == "paper-snapshot-test"


def test_projection_rejects_instrument_absent_from_signed_snapshot() -> None:
    universe = load_free_paper_pilot_universe()
    source = replace(universe, instruments=universe.instruments[:2])
    requested = replace(
        universe,
        instruments=(universe.instruments[0], universe.instruments[2]),
    )

    with pytest.raises(RuntimeError, match="absent from the signed snapshot"):
        qualified._validate_exact_evidence_subset(
            requested_universe=requested,
            source_universe=source,
        )


def test_projection_rejects_changed_instrument_contract() -> None:
    universe = load_free_paper_pilot_universe()
    source = replace(universe, instruments=universe.instruments[:2])
    changed = replace(source.instruments[0], venue="CHANGED")
    requested = replace(source, instruments=(changed,))

    with pytest.raises(RuntimeError, match="changed instrument contracts"):
        qualified._validate_exact_evidence_subset(
            requested_universe=requested,
            source_universe=source,
        )


def test_projection_rejects_changed_universe_evidence_contract() -> None:
    source = load_free_paper_pilot_universe()
    requested = replace(
        source,
        instruments=source.instruments[:1],
        maximum_quote_age_minutes=source.maximum_quote_age_minutes + 1,
    )

    with pytest.raises(RuntimeError, match="universe contract changed"):
        qualified._validate_exact_evidence_subset(
            requested_universe=requested,
            source_universe=source,
        )
