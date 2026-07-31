from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from intelligence.event_quality import (
    SQLiteEventClusterStore,
    assess_event_clusters,
    evaluate_benchmark,
)
from capital_intelligence_cli import main as cli_main


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "config" / "event_quality_benchmark.v1.json"


def _record(identifier, provider, *, group, canonical="event:rates", topic="Central bank changes rate guidance"):
    return {
        "identifier": identifier,
        "canonical_event_identifier": canonical,
        "topic": topic,
        "summary": "A material policy change affects discount rates.",
        "entities": ["Federal Reserve"],
        "instruments": ["instrument:TLT"],
        "impact_channels": ["policy", "discount_rate"],
        "reliability": 0.9,
        "relevance": 0.9,
        "materiality": 0.8,
        "provenance": {
            "provider": provider,
            "source_identifier": f"source:{identifier}",
            "independence_group": group,
        },
    }


def test_cluster_corroboration_confirmation_and_exposure_request_only_cio_review() -> None:
    result = assess_event_clusters(
        (_record("official", "Federal Reserve", group="official"), _record("wire", "Wire", group="wire")),
        owned_instruments=("instrument:TLT",),
        market_confirmation={"event:rates": 0.75},
    )
    assert len(result) == 1
    assessment, _ = result[0]
    assert assessment.independent_source_count == 2
    assert assessment.portfolio_exposures == ("instrument:TLT",)
    assert assessment.eligible_for_cio_context
    assert assessment.to_dict()["authorizes_portfolio_change"] is False
    assert assessment.to_dict()["real_money_authorized"] is False


def test_syndication_novelty_and_market_confirmation_fail_closed() -> None:
    syndicated = assess_event_clusters(
        (_record("a", "Outlet A", group="same-wire"), _record("b", "Outlet B", group="same-wire")),
        market_confirmation={"event:rates": 0.9},
    )[0][0]
    known = assess_event_clusters(
        (_record("a", "Official", group="official"), _record("b", "Wire", group="wire")),
        prior_semantic_keys=("event:rates",),
        market_confirmation={"event:rates": 0.9},
    )[0][0]
    unconfirmed = assess_event_clusters(
        (_record("a", "Official", group="official"), _record("b", "Wire", group="wire")),
        market_confirmation={"event:rates": 0.0},
    )[0][0]
    assert not syndicated.eligible_for_cio_context
    assert not known.eligible_for_cio_context
    assert not unconfirmed.eligible_for_cio_context


def test_false_entity_match_does_not_create_portfolio_exposure() -> None:
    record = _record("event", "Official", group="official")
    record["entities"] = ["Apple Bank Association"]
    assessment = assess_event_clusters(
        (record,),
        owned_instruments=("instrument:AAPL",),
        exposure_map={"Apple Inc.": ("instrument:AAPL",)},
    )[0][0]
    assert assessment.portfolio_exposures == ()


def test_cluster_store_is_idempotent_append_only(tmp_path) -> None:
    assessment = assess_event_clusters((_record("a", "Official", group="official"),))[0][0]
    store = SQLiteEventClusterStore(tmp_path / "events.db")
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    store.append(assessment, recorded_at=now)
    store.append(assessment, recorded_at=now)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM event_cluster_assessments").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM event_cluster_assessments")


def test_human_reviewed_benchmark_metrics_pass_and_are_certified() -> None:
    report = evaluate_benchmark(BENCHMARK)
    assert report["metrics_passed"]
    assert report["precision"] >= 0.8
    assert report["recall"] >= 0.8
    assert report["review_state"] == "approved"
    assert report["certified"]
    assert report["real_money_authorized"] is False


def test_benchmark_is_versioned_and_cannot_self_authorize() -> None:
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    assert payload["human_review"] == {
        "state": "approved",
        "reviewer": "LeVon Mendall, product owner",
        "reviewed_at": "2026-07-31T19:18:46Z",
        "instructions": "A human reviewer must verify every label and set state to approved before this benchmark is decision-certified.",
    }
    assert payload["authorizes_portfolio_change"] is False
    assert payload["real_money_authorized"] is False


def test_release_cli_accepts_human_approved_benchmark(tmp_path) -> None:
    result = cli_main(
        (
            "event-quality-benchmark",
            "--benchmark",
            str(BENCHMARK),
            "--report",
            str(tmp_path / "report.json"),
            "--require-certified",
        )
    )
    assert result == 0
