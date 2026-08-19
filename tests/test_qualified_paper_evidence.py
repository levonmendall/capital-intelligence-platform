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
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION", raising=False)


def _dynamic(template, *, suffix: str, symbol: str):
    return replace(
        template,
        symbol=symbol,
        instrument_identifier=f"{template.instrument_identifier}:{suffix}",
        name=f"Dynamic {suffix}",
    )


def test_production_probe_verifies_source_snapshot_then_projects_exact_subset(
    monkeypatch, tmp_path
) -> None:
    as_of = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)
    observed: dict[str, object] = {}
    base = load_free_paper_pilot_universe()
    dynamic_a = _dynamic(base.instruments[0], suffix="a", symbol="DYNA")
    dynamic_b = _dynamic(base.instruments[1], suffix="b", symbol="DYNB")
    source = replace(
        base,
        identifier="evidence-source:test",
        instruments=(*base.instruments, dynamic_a, dynamic_b),
    )
    requested = replace(
        base,
        identifier="capability-authorized:test",
        instruments=(*base.instruments, dynamic_a),
        limitations=(*base.limitations, "capability-scoped test subset"),
    )
    source_symbols = tuple(item.symbol for item in source.instruments)
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
    assert dynamic_b.symbol not in actual["bars"]
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
    base = load_free_paper_pilot_universe()
    dynamic_a = _dynamic(base.instruments[0], suffix="a", symbol="DYNA")
    dynamic_b = _dynamic(base.instruments[1], suffix="b", symbol="DYNB")
    source = replace(base, instruments=(*base.instruments, dynamic_a))
    requested = replace(base, instruments=(*base.instruments, dynamic_b))

    with pytest.raises(RuntimeError, match="absent from the signed snapshot"):
        qualified._validate_exact_evidence_subset(
            requested_universe=requested,
            source_universe=source,
        )


def test_projection_rejects_changed_instrument_contract() -> None:
    base = load_free_paper_pilot_universe()
    dynamic = _dynamic(base.instruments[0], suffix="a", symbol="DYNA")
    source = replace(base, instruments=(*base.instruments, dynamic))
    changed = replace(dynamic, venue="CHANGED")
    requested = replace(base, instruments=(*base.instruments, changed))

    with pytest.raises(RuntimeError, match="changed instrument contracts"):
        qualified._validate_exact_evidence_subset(
            requested_universe=requested,
            source_universe=source,
        )


def test_projection_rejects_changed_universe_evidence_contract() -> None:
    source = load_free_paper_pilot_universe()
    requested = replace(
        source,
        maximum_quote_age_minutes=source.maximum_quote_age_minutes + 1,
    )

    with pytest.raises(RuntimeError, match="universe contract changed"):
        qualified._validate_exact_evidence_subset(
            requested_universe=requested,
            source_universe=source,
        )
