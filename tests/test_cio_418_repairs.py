from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from operations import bounded_terminal_screening as bounded
from operations.market_discovery_preselection import (
    CandidateSleeve,
    CatalogScreeningSignal,
    build_preselection_plan,
)
from scripts import capture_render_production_telemetry as telemetry
from scripts import render_telemetry_commit_status as status


NOW = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)


def _record(index: int):
    symbol = f"R{index:03d}"
    return SimpleNamespace(
        symbol=symbol,
        provider_symbol=symbol,
        economic_exposure=f"sector-{index % 3}",
        venue=f"venue-{index % 2}",
        country_code=f"C{index % 2}",
        currency="USD",
    )


def _signal(index: int, symbol: str) -> CatalogScreeningSignal:
    return CatalogScreeningSignal(
        symbol=symbol,
        observed_at=NOW,
        eligible=True,
        liquidity_score=0.9,
        quality_score=0.2 + (index % 5) / 10,
        value_score=0.2 + (index % 4) / 10,
        momentum_score=0.2 + (index % 3) / 10,
        carry_score=0.5 if index % 2 else None,
        improving_conditions_score=0.3 + (index % 4) / 10,
        indicative_price=100.0 + index,
        evidence_identifiers=(f"provider-factor:value:test:{symbol}",),
    )


def test_disk_backed_finalization_preserves_global_round_robin_semantics() -> None:
    records = tuple(_record(index) for index in range(19))
    signals = {
        record.symbol: _signal(index, record.symbol)
        for index, record in enumerate(records)
    }
    expected = build_preselection_plan(
        records,
        signals,
        as_of=NOW,
        capacity=len(records),
        shadow_limit=0,
        freshness_days=3,
        minimum_liquidity_score=0.2,
    )

    with bounded._TerminalScreeningStateSpool() as spool:
        for ordinal, record in enumerate(records):
            spool.append(
                ordinal=ordinal,
                record=record,
                signal=signals[record.symbol],
                reasons=(),
                as_of=NOW,
            )
        spool.commit_chunk()
        spool.finalize_diversification(batch_size=3)
        spool.build_rankings(batch_size=3)
        assert spool.select_complete_consideration(capacity=len(records)) == len(records)
        assert spool.selected_symbols() == expected.selected_symbols
        assert tuple(
            (sleeve.value, spool.ranking(sleeve)) for sleeve in bounded.SLEEVES
        ) == expected.sleeve_rankings
        table_names = {
            row[0]
            for row in spool.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"screened", "rankings", "selection"}.issubset(table_names)


def _public_payload() -> dict[str, object]:
    return {
        "schema_version": "public-cio-diagnostic-audit.v1",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "active_release": "release-current",
        "release_matches": True,
        "state": "failed",
        "ready": False,
        "requested_at": "2026-08-12T17:00:00+00:00",
        "completed_at": "2026-08-12T17:10:00+00:00",
        "stage": "terminal_screening_chunk:international_equity",
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_complete": False,
        "scheduled_market_coverage_complete": False,
        "terminal_screening_complete": False,
        "all_market_evaluation_complete": False,
        "progress_metrics": {
            "processed_records": 45286,
            "total_records": 45286,
            "chunk_records": 38,
            "rss_kib": 198000,
            "service_rss_kib": 510000,
            "container_current_kib": 475000,
            "container_anon_kib": 408000,
            "container_file_kib": 61000,
            "governed_boundary_kib": 1441792,
            "governed_headroom_kib": 966792,
            "unknown_metric": 999,
        },
    }


def test_telemetry_preserves_only_allowlisted_progress_metrics() -> None:
    snapshot = telemetry.build_snapshot(
        _public_payload(),
        expected_release="release-current",
        captured_at=NOW,
    )
    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["stage"] == "terminal_screening_chunk:international_equity"
    metrics = diagnostic["progress_metrics"]
    assert isinstance(metrics, dict)
    assert metrics["processed_records"] == 45286.0
    assert metrics["container_anon_kib"] == 408000.0
    assert metrics["governed_headroom_kib"] == 966792.0
    assert "unknown_metric" not in metrics
    assert "unknown_metric" not in json.dumps(snapshot)


def test_lane_qualified_stage_survives_commit_status_formatting() -> None:
    snapshot = telemetry.build_snapshot(
        _public_payload(),
        expected_release="release-current",
        captured_at=NOW,
    )
    state_name, description = status.status_for_snapshot(snapshot)
    assert state_name == "error"
    assert "stage=terminal_screening_chunk:international_equity" in description
    assert "awaiting_progress" not in description
