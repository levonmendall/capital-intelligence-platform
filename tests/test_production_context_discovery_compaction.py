from __future__ import annotations

import gc
import weakref
from types import SimpleNamespace

from operations import production_context_discovery_compaction as subject


class _HeavyEvidence:
    pass


def test_equity_compaction_preserves_context_contract_without_selected_graph() -> None:
    heavy = _HeavyEvidence()
    heavy_ref = weakref.ref(heavy)
    instrument = SimpleNamespace(symbol="ABC", instrument_identifier="equity:ABC")
    result = SimpleNamespace(
        identifier="equity-discovery:1",
        as_of=object(),
        policy_version="equity.v1",
        screened_asset_count=10_000,
        snapshot_covered_count=9_900,
        deep_shortlist_count=400,
        selected=(heavy,),
        exclusions=(("ZZZ", heavy),),
        observed_prices=(("ABC", 101.0, "quote:ABC"),),
        security_master_snapshot_identifier="sec-master:1",
        instruments_for_holdings=lambda _held: (instrument,),
    )

    compact = subject._compact_equity_result(result, held_symbols=("ABC",))

    assert compact.identifier == "equity-discovery:1"
    assert compact.policy_version == "equity.v1"
    assert compact.screened_asset_count == 10_000
    assert compact.snapshot_covered_count == 9_900
    assert compact.deep_shortlist_count == 400
    assert len(compact.selected) == 1
    assert compact.observed_prices == (("ABC", 101.0, "quote:ABC"),)
    assert compact.security_master_snapshot_identifier == "sec-master:1"
    assert compact.instruments_for_holdings(("ABC",)) == (instrument,)
    assert not hasattr(compact, "exclusions")

    del result, heavy
    gc.collect()
    assert heavy_ref() is None


def test_comprehensive_compaction_preserves_terminal_accounting_without_lane_graph() -> None:
    heavy = _HeavyEvidence()
    heavy_ref = weakref.ref(heavy)
    instrument = SimpleNamespace(symbol="ES", instrument_identifier="future:ES")
    lane = SimpleNamespace(
        asset_class=SimpleNamespace(value="future"),
        catalog_count=50_000,
        deep_analyzed_count=4_000,
        scheduled=True,
        schedule_reason="scheduled",
        selected=(heavy,),
        exclusions=(("NQ", heavy),),
    )
    result = SimpleNamespace(
        identifier="comprehensive:1",
        manifest_fingerprint="fingerprint",
        policy_version="comprehensive.v1",
        scope_state="complete",
        limitations=("paper only",),
        lanes=(lane,),
        instruments_for_holdings=lambda _held: (instrument,),
    )

    compact = subject._compact_comprehensive_result(result, held_symbols=("ES",))

    assert compact.identifier == "comprehensive:1"
    assert compact.manifest_fingerprint == "fingerprint"
    assert compact.policy_version == "comprehensive.v1"
    assert compact.scope_state == "complete"
    assert compact.limitations == ("paper only",)
    assert compact.instruments_for_holdings(("ES",)) == (instrument,)
    assert len(compact.lanes) == 1
    assert compact.lanes[0].asset_class.value == "future"
    assert compact.lanes[0].catalog_count == 50_000
    assert compact.lanes[0].deep_analyzed_count == 4_000
    assert compact.lanes[0].scheduled is True
    assert compact.lanes[0].schedule_reason == "scheduled"
    assert len(compact.lanes[0].selected) == 1

    del result, lane, heavy
    gc.collect()
    assert heavy_ref() is None


def test_installer_changes_only_production_context_discovery_seams(monkeypatch) -> None:
    monkeypatch.delattr(subject._governed, subject._INSTALLED_ATTR, raising=False)
    original_equity = subject._governed.discover_us_equities
    original_comprehensive = subject._governed._discover_comprehensive_scope

    subject.install()

    assert subject._governed.discover_us_equities is subject._compact_discover_us_equities
    assert (
        subject._governed._discover_comprehensive_scope
        is subject._compact_discover_comprehensive_scope
    )
    assert getattr(subject._governed, subject._INSTALLED_ATTR) is True

    subject.install()
    assert subject._governed.discover_us_equities is subject._compact_discover_us_equities
    assert (
        subject._governed._discover_comprehensive_scope
        is subject._compact_discover_comprehensive_scope
    )

    monkeypatch.setattr(subject._governed, "discover_us_equities", original_equity)
    monkeypatch.setattr(
        subject._governed,
        "_discover_comprehensive_scope",
        original_comprehensive,
    )


def test_compaction_does_not_change_resource_or_investment_policy() -> None:
    source = __import__("pathlib").Path(
        "operations/production_context_discovery_compaction.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "governed_boundary",
        "memory_reserve",
        "memory.max",
        "drop_caches",
        "candidate_authority",
        "decision_authority",
        "execution_authority",
        "real_money_authorized = True",
    ):
        assert forbidden not in source


def test_render_bootstrap_installs_compaction_before_final_evidence_seam() -> None:
    source = __import__("pathlib").Path("run_render_service_workspace.py").read_text(
        encoding="utf-8"
    )

    compaction = source.index("install_production_context_discovery_compaction()")
    evidence = source.index("install_single_pass_marked_paper_evidence()")
    assert compaction < evidence
