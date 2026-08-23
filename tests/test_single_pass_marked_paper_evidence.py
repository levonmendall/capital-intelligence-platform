from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from operations import single_pass_marked_paper_evidence as subject


def test_build_holding_marks_uses_base_feature_path_without_predictive_enrichment(monkeypatch) -> None:
    as_of = datetime(2026, 8, 23, 1, 40, tzinfo=timezone.utc)
    universe = SimpleNamespace(
        instruments=(SimpleNamespace(symbol="VTI"),),
        maximum_quote_age_minutes=20,
    )
    portfolio = SimpleNamespace(
        as_of=as_of,
        positions=(SimpleNamespace(symbol="VTI"),),
        nav=250_000.0,
    )
    bars = object()
    quote = object()
    observed = {}

    def base_features(symbol, raw_bars, raw_quote, **kwargs):
        observed.update(symbol=symbol, bars=raw_bars, quote=raw_quote, kwargs=kwargs)
        return SimpleNamespace(current_price=321.25)

    monkeypatch.setattr(subject._evidence, "_ORIGINAL_FEATURES", base_features)
    monkeypatch.setattr(
        subject._evidence,
        "_features",
        lambda *_args, **_kwargs: pytest.fail(
            "mark-only pass must not run predictive feature enrichment"
        ),
    )
    marks = subject.build_holding_marks(
        universe=universe,
        decision_as_of=as_of,
        cash_expected_return=0.04,
        portfolio=portfolio,
        payload={"bars": {"VTI": bars}, "quotes": {"VTI": quote}},
    )

    assert marks == (("VTI", 321.25),)
    assert observed["symbol"] == "VTI"
    assert observed["bars"] is bars
    assert observed["quote"] is quote
    assert observed["kwargs"]["as_of"] == as_of
    assert observed["kwargs"]["cash_expected_return"] == 0.04
    assert observed["kwargs"]["maximum_quote_age_minutes"] == 20
    assert observed["kwargs"]["maximum_future_skew_seconds"] == 0
    assert observed["kwargs"]["future_reference_at"] == as_of


def test_build_holding_marks_preserves_live_provider_clock_gate(monkeypatch) -> None:
    as_of = datetime(2026, 8, 23, 1, 40, tzinfo=timezone.utc)
    universe = SimpleNamespace(
        instruments=(SimpleNamespace(symbol="VTI"),),
        maximum_quote_age_minutes=20,
    )
    portfolio = SimpleNamespace(
        as_of=as_of,
        positions=(SimpleNamespace(symbol="VTI"),),
        nav=250_000.0,
    )
    observed = {}

    def base_features(_symbol, _bars, _quote, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(current_price=100.0)

    monkeypatch.setattr(subject._evidence, "_ORIGINAL_FEATURES", base_features)
    marks = subject.build_holding_marks(
        universe=universe,
        decision_as_of=as_of,
        cash_expected_return=0.03,
        portfolio=portfolio,
        payload={
            "bars": {"VTI": object()},
            "quotes": {"VTI": object()},
            "_live_collection": True,
            "provider_clock": {"timestamp": as_of.isoformat()},
        },
    )

    assert marks == (("VTI", 100.0),)
    assert observed["maximum_future_skew_seconds"] == -1
    assert observed["future_reference_at"] == as_of


def test_missing_base_feature_builder_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(subject._evidence, "_ORIGINAL_FEATURES", None)

    with pytest.raises(
        subject._evidence.ProductionPaperEvidenceError,
        match="base feature extractor is unavailable",
    ):
        subject._base_feature_builder()


def test_positioned_portfolio_builds_complete_evidence_once(monkeypatch) -> None:
    as_of = datetime(2026, 8, 23, 1, 40, tzinfo=timezone.utc)
    tentative = SimpleNamespace(positions=(SimpleNamespace(symbol="VTI"),))
    marked = SimpleNamespace(positions=tentative.positions, marker="marked")
    marks = (("VTI", 101.0),)
    result = SimpleNamespace(holding_marks=marks, candidates=())
    build_calls = []
    mark_calls = []
    progress = []

    monkeypatch.setattr(subject, "build_holding_marks", lambda **_kwargs: marks)

    def mark_portfolio(snapshot, build_result, *, decision_as_of):
        mark_calls.append((snapshot, build_result, decision_as_of))
        return marked

    def build_paper_evidence(**kwargs):
        build_calls.append(kwargs)
        return result

    monkeypatch.setattr(subject._governed, "_mark_portfolio", mark_portfolio)
    monkeypatch.setattr(subject._governed, "build_paper_evidence", build_paper_evidence)

    observed_marked, observed_result = subject._single_pass_build_marked_paper_evidence(
        universe=object(),
        decision_as_of=as_of,
        cash_expected_return=0.04,
        tentative=tentative,
        evidence_payload={"bars": {}, "quotes": {}},
        progress_probe=progress.append,
    )

    assert observed_marked is marked
    assert observed_result is result
    assert len(build_calls) == 1
    assert build_calls[0]["portfolio"] is marked
    assert len(mark_calls) == 2
    assert progress == [
        "production_context_holding_marks_started",
        "production_context_preliminary_evidence_built",
        "production_context_portfolio_marked",
        "production_context_evidence_built",
    ]


def test_final_holding_mark_mismatch_fails_closed(monkeypatch) -> None:
    as_of = datetime(2026, 8, 23, 1, 40, tzinfo=timezone.utc)
    tentative = SimpleNamespace(positions=(SimpleNamespace(symbol="VTI"),))
    marked = SimpleNamespace(positions=tentative.positions, marker="marked")
    preliminary_marks = (("VTI", 101.0),)
    final_result = SimpleNamespace(holding_marks=(("VTI", 102.0),), candidates=())

    monkeypatch.setattr(subject, "build_holding_marks", lambda **_kwargs: preliminary_marks)
    monkeypatch.setattr(subject._governed, "_mark_portfolio", lambda *_args, **_kwargs: marked)
    monkeypatch.setattr(subject._governed, "build_paper_evidence", lambda **_kwargs: final_result)

    with pytest.raises(
        subject._evidence.ProductionPaperEvidenceError,
        match="holding marks differ",
    ):
        subject._single_pass_build_marked_paper_evidence(
            universe=object(),
            decision_as_of=as_of,
            cash_expected_return=0.04,
            tentative=tentative,
            evidence_payload={},
            progress_probe=None,
        )


def test_holding_mark_failure_never_builds_complete_graph_and_records_boundary(monkeypatch) -> None:
    tentative = SimpleNamespace(positions=(SimpleNamespace(symbol="VTI"),))
    progress = []

    def fail_marks(**_kwargs):
        raise subject._evidence.ProductionPaperEvidenceError("mandatory holding failed")

    monkeypatch.setattr(subject, "build_holding_marks", fail_marks)
    monkeypatch.setattr(
        subject._governed,
        "build_paper_evidence",
        lambda **_kwargs: pytest.fail("complete evidence must not build after mark failure"),
    )

    with pytest.raises(
        subject._evidence.ProductionPaperEvidenceError,
        match="mandatory holding failed",
    ):
        subject._single_pass_build_marked_paper_evidence(
            universe=object(),
            decision_as_of=datetime(2026, 8, 23, tzinfo=timezone.utc),
            cash_expected_return=0.04,
            tentative=tentative,
            evidence_payload={},
            progress_probe=progress.append,
        )

    assert progress == [
        "production_context_holding_marks_started",
        "production_context_holding_marks_failed",
    ]


def test_cash_only_portfolio_keeps_original_single_build_path(monkeypatch) -> None:
    tentative = SimpleNamespace(positions=())
    expected = (tentative, object())
    observed = {}

    def original(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(subject, "_ORIGINAL_BUILD_MARKED_PAPER_EVIDENCE", original)
    monkeypatch.setattr(
        subject,
        "build_holding_marks",
        lambda **_kwargs: pytest.fail("cash-only path must not build holding marks"),
    )

    result = subject._single_pass_build_marked_paper_evidence(
        universe="universe",
        decision_as_of=datetime(2026, 8, 23, tzinfo=timezone.utc),
        cash_expected_return=0.04,
        tentative=tentative,
        evidence_payload={"payload": True},
        progress_probe=None,
    )

    assert result == expected
    assert observed["tentative"] is tentative
    assert observed["universe"] == "universe"


def test_install_replaces_only_marked_evidence_seam(monkeypatch) -> None:
    original = object()
    monkeypatch.setattr(subject._governed, "_build_marked_paper_evidence", original)
    monkeypatch.setattr(subject._governed, subject._INSTALLED_ATTR, False, raising=False)

    subject.install()

    assert subject._governed._build_marked_paper_evidence is subject._single_pass_build_marked_paper_evidence
    assert getattr(subject._governed, subject._INSTALLED_ATTR) is True
