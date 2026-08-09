from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import production_context_publication_governed as governed
import production_paper_evidence_impl as evidence
from cio import CandidateAssetClass
from operations.free_paper_pilot import FreePaperPilotInstrument, FreePaperPilotUniverse


def _instrument(symbol: str, *, asset_class=CandidateAssetClass.US_EQUITY, instrument_type="common_stock"):
    return FreePaperPilotInstrument(
        symbol=symbol,
        instrument_identifier=f"instrument:test:{symbol.lower()}",
        name=symbol,
        execution_asset_class=asset_class,
        economic_exposure="us_equity",
        venue="NYSE",
        country_code="US",
        currency="USD",
        instrument_type=instrument_type,
        maximum_weight=0.05,
        issuer_cik="0000063908" if instrument_type == "common_stock" else None,
    )


def _universe(identifier: str, instruments):
    return FreePaperPilotUniverse(
        identifier=identifier,
        objective="test",
        portfolio_code="COMPOUNDING",
        reporting_currency="USD",
        quote_provider="ALPACA_IEX",
        execution_mode="paper",
        minimum_cash_weight=0.0,
        maximum_batch_turnover=1.0,
        maximum_single_instrument_weight=0.10,
        maximum_crypto_proxy_weight=0.10,
        maximum_volatility_proxy_weight=0.10,
        maximum_quote_age_minutes=30,
        required_exposure_classes=(),
        instruments=tuple(instruments),
        limitations=(),
    )


def test_missing_canonical_holding_is_carried_only_from_prior_certified_universe(monkeypatch, tmp_path):
    current = _universe("current", (_instrument("VTI", asset_class=CandidateAssetClass.US_ETF, instrument_type="fund"),))
    mcd = _instrument("MCD")
    prior = _universe("prior", (*current.instruments, mcd))
    monkeypatch.setattr(
        governed,
        "load_current_active_paper_universe",
        lambda **_kwargs: ("eligible:prior", prior),
    )
    reconciled, evidence_only = governed._reconcile_canonical_holding_evidence_scope(
        settings=SimpleNamespace(portfolio_database=tmp_path / "portfolio.db"),
        universe=current,
        portfolio=SimpleNamespace(positions=(SimpleNamespace(symbol="MCD"),)),
    )
    assert evidence_only == ("MCD",)
    assert set(reconciled.symbol_map) == {"VTI", "MCD"}
    assert reconciled.symbol_map["MCD"] == mcd


def test_holding_only_evidence_cannot_become_a_candidate(monkeypatch):
    as_of = datetime(2026, 8, 8, 18, 0, tzinfo=timezone.utc)
    mcd = _instrument("MCD")
    universe = _universe("current+hold", (mcd,))
    feature = SimpleNamespace(
        symbol="MCD",
        current_price=100.0,
        latest_observed_at=as_of,
        average_daily_dollar_volume=100_000_000.0,
    )
    monkeypatch.setattr(evidence, "_macro_context", lambda *_args, **_kwargs: (SimpleNamespace(), {}, ("macro",)))
    monkeypatch.setattr(evidence, "_features", lambda *_args, **_kwargs: feature)
    monkeypatch.setattr(evidence, "_holding_evidence", lambda *_args, **_kwargs: "holding-evidence")
    portfolio = SimpleNamespace(
        as_of=as_of,
        positions=(SimpleNamespace(symbol="MCD", market_value=100.0),),
        nav=1_000.0,
    )
    result = evidence.build_paper_evidence(
        universe=universe,
        decision_as_of=as_of,
        cash_expected_return=0.04,
        portfolio=portfolio,
        payload={
            "bars": {"MCD": object()},
            "quotes": {"MCD": object()},
            "macro": {},
            "company_facts": {},
            "_scheduled_closed_symbols": (),
            "_holding_only_symbols": ("MCD",),
        },
    )
    assert result.candidates == ()
    assert result.candidate_evidence == ()
    assert result.holding_evidence == ("holding-evidence",)
    assert result.holding_marks == (("MCD", 100.0),)
    assert result.exclusions[0][0] == mcd.instrument_identifier


def test_holding_only_marker_rejects_non_held_instrument(monkeypatch):
    as_of = datetime(2026, 8, 8, 18, 0, tzinfo=timezone.utc)
    mcd = _instrument("MCD")
    universe = _universe("current+hold", (mcd,))
    monkeypatch.setattr(evidence, "_macro_context", lambda *_args, **_kwargs: (SimpleNamespace(), {}, ("macro",)))
    portfolio = SimpleNamespace(as_of=as_of, positions=(), nav=1_000.0)
    try:
        evidence.build_paper_evidence(
            universe=universe,
            decision_as_of=as_of,
            cash_expected_return=0.04,
            portfolio=portfolio,
            payload={
                "bars": {},
                "quotes": {},
                "macro": {},
                "_scheduled_closed_symbols": (),
                "_holding_only_symbols": ("MCD",),
            },
        )
    except evidence.ProductionPaperEvidenceError as error:
        assert "cannot admit non-held instruments" in str(error)
    else:
        raise AssertionError("non-held holding-only marker must fail closed")


@dataclass(frozen=True)
class _TestPosition:
    symbol: str
    mark_price: float
    updated_at: datetime


@dataclass(frozen=True)
class _TestSnapshot:
    positions: tuple[_TestPosition, ...]


def test_mark_portfolio_uses_certified_holding_mark_without_candidate_nomination():
    as_of = datetime(2026, 8, 8, 18, 0, tzinfo=timezone.utc)
    snapshot = _TestSnapshot(
        positions=(
            _TestPosition(
                symbol="MCD",
                mark_price=95.0,
                updated_at=as_of - timedelta(days=1),
            ),
        )
    )
    build_result = SimpleNamespace(
        candidates=(),
        holding_marks=(("MCD", 100.0),),
    )

    marked = governed._mark_portfolio(
        snapshot,
        build_result,
        decision_as_of=as_of,
    )

    assert marked.positions[0].mark_price == 100.0
    assert marked.positions[0].updated_at == as_of
    assert build_result.candidates == ()


def test_mark_portfolio_rejects_mark_for_non_holding():
    as_of = datetime(2026, 8, 8, 18, 0, tzinfo=timezone.utc)
    snapshot = _TestSnapshot(
        positions=(_TestPosition("MCD", 95.0, as_of - timedelta(days=1)),)
    )
    build_result = SimpleNamespace(
        candidates=(),
        holding_marks=(("VTI", 200.0),),
    )

    try:
        governed._mark_portfolio(snapshot, build_result, decision_as_of=as_of)
    except governed.ProductionPaperEvidenceError as error:
        assert "non-held instruments" in str(error)
    else:
        raise AssertionError("non-held holding mark must fail closed")


def test_mark_portfolio_still_fails_closed_without_certified_holding_mark():
    as_of = datetime(2026, 8, 8, 18, 0, tzinfo=timezone.utc)
    snapshot = _TestSnapshot(
        positions=(_TestPosition("MCD", 95.0, as_of - timedelta(days=1)),)
    )
    build_result = SimpleNamespace(candidates=(), holding_marks=())

    try:
        governed._mark_portfolio(snapshot, build_result, decision_as_of=as_of)
    except governed.ProductionPaperEvidenceError as error:
        assert "current marks are unavailable" in str(error)
    else:
        raise AssertionError("missing certified holding mark must fail closed")
