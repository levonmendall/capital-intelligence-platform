from __future__ import annotations

import gc
import weakref
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from operations import production_context_discovery_compaction as subject
from portfolio.constants import (
    CANONICAL_CONSTRAINT_PROFILE,
    CANONICAL_PORTFOLIO_CODE,
    CANONICAL_PORTFOLIO_NAME,
    INITIAL_PAPER_CAPITAL,
)
from portfolio.state import (
    CanonicalPortfolioIntegrityError,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)


class _HeavyEvidence:
    pass


def _portfolio_snapshot(identifier: str, as_of: datetime) -> CanonicalPortfolioSnapshot:
    return CanonicalPortfolioSnapshot(
        identifier=identifier,
        portfolio_code=CANONICAL_PORTFOLIO_CODE,
        display_name=CANONICAL_PORTFOLIO_NAME,
        constraint_profile=CANONICAL_CONSTRAINT_PROFILE,
        as_of=as_of,
        starting_capital=INITIAL_PAPER_CAPITAL,
        cash_amount=INITIAL_PAPER_CAPITAL,
        positions=(),
        source_identifiers=("test-source",),
    )


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


def test_bounded_tentative_portfolio_avoids_eager_history_rehydration(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.sqlite3")
    as_of = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    expected = _portfolio_snapshot("portfolio:test:exact", as_of)
    store.append(expected)

    def forbidden_history(*_args, **_kwargs):
        raise AssertionError("eager canonical history must not be materialized")

    def forbidden_legacy_integrity():
        raise AssertionError("fetchall integrity verification must not be used")

    monkeypatch.setattr(store, "history", forbidden_history)
    monkeypatch.setattr(store, "verify_integrity", forbidden_legacy_integrity)

    observed, exact = subject._bounded_tentative_portfolio(
        store=store,
        decision_as_of=as_of.astimezone(timezone(timedelta(hours=-7))),
        context_identifier="context:test",
    )

    assert exact is True
    assert observed == expected


def test_bounded_tentative_portfolio_preserves_latest_history_fallback(tmp_path) -> None:
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.sqlite3")
    prior_as_of = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    decision_as_of = prior_as_of + timedelta(minutes=5)
    store.append(_portfolio_snapshot("portfolio:test:prior", prior_as_of))

    observed, exact = subject._bounded_tentative_portfolio(
        store=store,
        decision_as_of=decision_as_of,
        context_identifier="context:test",
    )

    assert exact is False
    assert observed.as_of == decision_as_of
    assert observed.identifier == "portfolio:compounding:decision:20260830T120500000000Z"
    assert observed.cash_amount == INITIAL_PAPER_CAPITAL
    assert observed.source_identifiers == ("test-source", "context:test")


def test_bounded_tentative_portfolio_still_fails_closed_on_duplicate_exact_time(
    tmp_path,
) -> None:
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.sqlite3")
    as_of = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    store.append(_portfolio_snapshot("portfolio:test:first", as_of))
    store.append(_portfolio_snapshot("portfolio:test:second", as_of))

    with pytest.raises(
        subject._governed.ProductionPaperEvidenceError,
        match="multiple canonical portfolio snapshots exist at the decision timestamp",
    ):
        subject._bounded_tentative_portfolio(
            store=store,
            decision_as_of=as_of,
            context_identifier="context:test",
        )


def test_streaming_integrity_verification_remains_fail_closed(tmp_path) -> None:
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.sqlite3")
    first_as_of = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    store.append(_portfolio_snapshot("portfolio:test:first", first_as_of))
    store.append(
        _portfolio_snapshot(
            "portfolio:test:second",
            first_as_of + timedelta(minutes=1),
        )
    )
    with store._connect() as connection:
        connection.execute("DROP TRIGGER canonical_portfolio_no_update")
        connection.execute(
            "UPDATE canonical_portfolio_events SET previous_hash = ? WHERE sequence = 2",
            ("f" * 64,),
        )

    with pytest.raises(
        CanonicalPortfolioIntegrityError,
        match="previous-hash link is invalid",
    ):
        subject._verify_canonical_integrity_streaming(store)


def test_installer_changes_only_production_context_bounded_handoff_seams() -> None:
    original_equity = subject._governed.discover_us_equities
    original_comprehensive = subject._governed._discover_comprehensive_scope
    original_tentative = subject._governed._tentative_portfolio
    had_installed = hasattr(subject._governed, subject._INSTALLED_ATTR)
    prior_installed = getattr(subject._governed, subject._INSTALLED_ATTR, None)
    if had_installed:
        delattr(subject._governed, subject._INSTALLED_ATTR)

    try:
        subject.install()

        assert subject._governed.discover_us_equities is subject._compact_discover_us_equities
        assert (
            subject._governed._discover_comprehensive_scope
            is subject._compact_discover_comprehensive_scope
        )
        assert subject._governed._tentative_portfolio is subject._bounded_tentative_portfolio
        assert getattr(subject._governed, subject._INSTALLED_ATTR) is True

        subject.install()
        assert subject._governed.discover_us_equities is subject._compact_discover_us_equities
        assert (
            subject._governed._discover_comprehensive_scope
            is subject._compact_discover_comprehensive_scope
        )
        assert subject._governed._tentative_portfolio is subject._bounded_tentative_portfolio
    finally:
        subject._governed.discover_us_equities = original_equity
        subject._governed._discover_comprehensive_scope = original_comprehensive
        subject._governed._tentative_portfolio = original_tentative
        if had_installed:
            setattr(subject._governed, subject._INSTALLED_ATTR, prior_installed)
        elif hasattr(subject._governed, subject._INSTALLED_ATTR):
            delattr(subject._governed, subject._INSTALLED_ATTR)


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
