from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from operations import capability_operating_evidence as evidence
from operations import capability_operating_universe as operating_universe
from operations.free_paper_pilot import load_free_paper_pilot_universe


AS_OF = datetime(2026, 8, 19, 19, 30, tzinfo=timezone.utc)


def _dynamic(item, *, suffix: str, symbol: str):
    return replace(
        item,
        symbol=symbol,
        instrument_identifier=f"{item.instrument_identifier}:{suffix}",
        name=f"Dynamic {suffix}",
    )


def test_operating_universe_is_base_only_without_active_publication(monkeypatch):
    base = load_free_paper_pilot_universe()
    monkeypatch.setattr(operating_universe, "_load_active_publication", lambda: None)
    monkeypatch.setattr(
        operating_universe,
        "load_current_authorized_universe",
        lambda **_kwargs: None,
    )

    actual, holding_only = operating_universe.build_capability_operating_universe(
        as_of=AS_OF,
    )

    assert actual.instruments == base.instruments
    assert holding_only == ()


def test_operating_universe_keeps_suspended_holding_as_evidence_only(monkeypatch):
    base = load_free_paper_pilot_universe()
    authorized_dynamic = _dynamic(base.instruments[0], suffix="authorized", symbol="AUTH")
    suspended_holding = _dynamic(base.instruments[1], suffix="held", symbol="HELD")
    raw_active = replace(
        base,
        identifier="active:test",
        instruments=(*base.instruments, authorized_dynamic, suspended_holding),
    )
    authorized = replace(
        base,
        identifier="authorized:test",
        instruments=(*base.instruments, authorized_dynamic),
    )

    monkeypatch.setattr(
        operating_universe,
        "_load_active_publication",
        lambda: (operating_universe.Path("active.json"), "eligible:test", raw_active),
    )
    monkeypatch.setattr(
        operating_universe,
        "load_current_authorized_universe",
        lambda **_kwargs: authorized,
    )

    actual, holding_only = operating_universe.build_capability_operating_universe(
        as_of=AS_OF,
        held_symbols=(suspended_holding.symbol,),
    )

    assert authorized_dynamic in actual.instruments
    assert suspended_holding in actual.instruments
    assert holding_only == (suspended_holding.symbol,)


def test_operating_universe_fails_closed_for_unresolved_dynamic_holding(monkeypatch):
    base = load_free_paper_pilot_universe()
    monkeypatch.setattr(
        operating_universe,
        "_load_active_publication",
        lambda: (operating_universe.Path("active.json"), "eligible:test", base),
    )
    monkeypatch.setattr(
        operating_universe,
        "load_current_authorized_universe",
        lambda **_kwargs: base,
    )

    with pytest.raises(ValueError, match="cannot be resolved"):
        operating_universe.build_capability_operating_universe(
            as_of=AS_OF,
            held_symbols=("UNKNOWN-HOLDING",),
        )


def test_operating_evidence_degrades_optional_dynamic_scope_before_failing_portfolio(
    monkeypatch, tmp_path
):
    base = load_free_paper_pilot_universe()
    dynamic = _dynamic(base.instruments[0], suffix="optional", symbol="OPTIONAL")
    full = replace(
        base,
        identifier="operating:full",
        instruments=(*base.instruments, dynamic),
    )
    calls: list[tuple[str, ...]] = []
    published: dict[str, object] = {}

    monkeypatch.setattr(
        evidence,
        "load_evidence_state_scope",
        lambda **_kwargs: SimpleNamespace(held_symbols=()),
    )
    monkeypatch.setattr(
        evidence,
        "build_capability_operating_universe",
        lambda **_kwargs: (full, ()),
    )

    def collect(universe, *_args, **_kwargs):
        symbols = tuple(item.symbol for item in universe.instruments)
        calls.append(symbols)
        if dynamic.symbol in symbols:
            raise RuntimeError("optional provider degraded")
        return {"bars": {}, "quotes": {}, "macro": {}, "provider_clock": {}}

    def publish(payload, *, universe, **_kwargs):
        published["universe"] = universe
        published["payload"] = payload
        return SimpleNamespace(snapshot_id="snapshot:minimum", payload=payload)

    monkeypatch.setattr(evidence, "collect_owned_paper_evidence", collect)
    monkeypatch.setattr(evidence, "publish_paper_evidence_snapshot", publish)
    monkeypatch.setattr(evidence, "close_spooled_paper_evidence", lambda _payload: None)

    actual = evidence.refresh_capability_operating_evidence(
        as_of=AS_OF,
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
    )

    assert len(calls) == 2
    assert dynamic.symbol in calls[0]
    assert dynamic.symbol not in calls[1]
    assert actual.universe.instruments == base.instruments
    state = evidence._read_state({"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)})
    assert state["scope_state"] == "degraded_bootstrap_and_holdings"
    assert state["instrument_count"] == len(base.instruments)
    assert state["full_operating_instrument_count"] == len(full.instruments)


def test_minimum_portfolio_evidence_failure_remains_fail_closed(monkeypatch, tmp_path):
    base = load_free_paper_pilot_universe()
    dynamic = _dynamic(base.instruments[0], suffix="optional", symbol="OPTIONAL")
    full = replace(base, instruments=(*base.instruments, dynamic))

    monkeypatch.setattr(
        evidence,
        "load_evidence_state_scope",
        lambda **_kwargs: SimpleNamespace(held_symbols=()),
    )
    monkeypatch.setattr(
        evidence,
        "build_capability_operating_universe",
        lambda **_kwargs: (full, ()),
    )
    monkeypatch.setattr(
        evidence,
        "collect_owned_paper_evidence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    with pytest.raises(
        evidence.CapabilityOperatingEvidenceError,
        match="minimum bootstrap/holding evidence refresh failed",
    ):
        evidence.refresh_capability_operating_evidence(
            as_of=AS_OF,
            values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        )
