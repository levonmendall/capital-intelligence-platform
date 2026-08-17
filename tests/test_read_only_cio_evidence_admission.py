from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from operations import owned_paper_evidence_collection as owned
from operations import qualified_paper_evidence as qualified
import production_context_publication_governed as governed
import production_context_publication_runtime as runtime


NOW = datetime(2026, 8, 17, 17, 0, tzinfo=timezone.utc)


def test_evidence_owner_acquires_and_embeds_paper_readiness(monkeypatch) -> None:
    calls: list[object] = []
    client = object()
    base_universe = object()
    readiness = SimpleNamespace(
        evaluated_at=NOW,
        universe_identifier="free-paper-pilot:v1",
        configuration_ready=True,
        execution_ready_now=True,
        market_open=True,
        account_status="ACTIVE",
        validated_symbols=("SPY", "VTI"),
        quote_timestamps=(("SPY", NOW.isoformat()), ("VTI", NOW.isoformat())),
        blockers=(),
        warnings=(),
    )
    monkeypatch.setattr(
        owned,
        "collect_spooled_paper_evidence",
        lambda *_args, **_kwargs: {
            "bars": {},
            "quotes": {},
            "macro": {},
            "provider_clock": {"timestamp": NOW.isoformat(), "is_open": True},
        },
    )
    monkeypatch.setattr(owned, "load_free_paper_pilot_universe", lambda: base_universe)
    monkeypatch.setattr(owned, "create_complete_alpaca_paper_client", lambda: client)

    def assess(*, universe, client):
        calls.extend((universe, client))
        return readiness

    monkeypatch.setattr(owned, "assess_free_paper_pilot_readiness", assess)

    payload = owned.collect_owned_paper_evidence(object(), NOW, values={})

    assert calls == [base_universe, client]
    persisted = payload["provider_clock"]["paper_readiness"]
    assert persisted["account_status"] == "ACTIVE"
    assert persisted["configuration_ready"] is True
    assert persisted["validated_symbols"] == ["SPY", "VTI"]


def test_qualified_admission_reads_readiness_and_cash_without_acquisition(monkeypatch) -> None:
    readiness = {
        "universe_identifier": "free-paper-pilot:v1",
        "configuration_ready": True,
        "execution_ready_now": False,
        "market_open": False,
        "account_status": "ACTIVE",
        "validated_symbols": ["SPY"],
        "quote_timestamps": [["SPY", NOW.isoformat()]],
        "blockers": [],
        "warnings": [],
    }
    dgs10 = SimpleNamespace(date="2026-08-17", value=4.25)
    snapshot = SimpleNamespace(
        payload={
            "provider_clock": {"paper_readiness": readiness},
            "macro": {"DGS10": dgs10},
        }
    )
    monkeypatch.setattr(qualified, "_qualified_snapshot_for_cutoff", lambda _cutoff: snapshot)

    actual_readiness = qualified.qualified_paper_readiness_probe(
        SimpleNamespace(identifier="free-paper-pilot:v1"), cutoff=NOW
    )
    actual_cash = qualified.qualified_cash_probe(cutoff=NOW)

    assert actual_readiness == readiness
    assert actual_cash is dgs10


def test_qualified_admission_fails_closed_on_incomplete_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        qualified,
        "_qualified_snapshot_for_cutoff",
        lambda _cutoff: SimpleNamespace(payload={"provider_clock": {}, "macro": {}}),
    )

    with pytest.raises(RuntimeError, match="readiness metadata is unavailable"):
        qualified.qualified_paper_readiness_probe(
            SimpleNamespace(identifier="free-paper-pilot:v1"), cutoff=NOW
        )
    with pytest.raises(RuntimeError, match="DGS10"):
        qualified.qualified_cash_probe(cutoff=NOW)


def test_production_context_defaults_all_admission_probes_to_qualified_snapshots(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    readiness_cutoffs: list[datetime] = []
    cash_cutoffs: list[datetime] = []

    def readiness(_universe, *, cutoff):
        readiness_cutoffs.append(cutoff)
        return object()

    def cash(*, cutoff):
        cash_cutoffs.append(cutoff)
        return object()

    def evidence(_universe, _as_of):
        return object()

    monkeypatch.setattr(qualified, "production_snapshot_probe_enabled", lambda: True)
    monkeypatch.setattr(qualified, "qualified_paper_readiness_probe", readiness)
    monkeypatch.setattr(qualified, "qualified_cash_probe", cash)
    monkeypatch.setattr(qualified, "qualified_paper_evidence_probe", evidence)
    monkeypatch.setattr(
        runtime,
        "_default_readiness_probe",
        lambda _universe: (_ for _ in ()).throw(
            AssertionError("live Alpaca readiness acquisition is forbidden")
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_default_cash_probe",
        lambda: (_ for _ in ()).throw(
            AssertionError("live FRED cash acquisition is forbidden")
        ),
    )

    def prepare(**kwargs):
        captured.update(kwargs)
        kwargs["readiness_probe"](SimpleNamespace(identifier="free-paper-pilot:v1"))
        kwargs["cash_probe"]()
        return runtime.ProductionContextPublicationResult(
            state="blocked",
            cycle_key="canonical-cio:test",
            scheduled_for=kwargs["scheduled_for"],
            decision_as_of=None,
            detail="fixture",
        )

    monkeypatch.setattr(governed, "prepare_governed_production_context_for_cycle", prepare)

    runtime.prepare_production_context_for_cycle(
        settings=SimpleNamespace(),
        scheduled_for=NOW,
    )

    assert captured["evidence_probe"] is evidence
    assert callable(captured["clock"])
    assert len(readiness_cutoffs) == 1
    assert cash_cutoffs == readiness_cutoffs
    assert captured["clock"]() == readiness_cutoffs[0]
