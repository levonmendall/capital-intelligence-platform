"""Tests for controlled paper-test readiness while development remains open."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from governance import (
    ProductTestReadiness,
    ProductTestReadinessEvidence,
    ProductTestReadinessEvaluator,
    SQLiteProductTestReadinessStore,
    TestReadinessIntegrityError,
)

NOW = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)


def _evidence(**overrides) -> ProductTestReadinessEvidence:
    values = {
        "identifier": "assessment:2026-07-27",
        "assessed_at": NOW,
        "test_baseline_identifier": "test-baseline:multi-asset-alpha.1",
        "process_version": "capital-intelligence-investment-process.v1-test",
        "code_version": "commit:test",
        "development_remains_open": True,
        "core_us_market_ready": True,
        "crypto_market_ready": True,
        "spot_fx_market_ready": True,
        "international_equity_market_ready": True,
        "fixed_income_market_ready": True,
        "commodity_market_ready": True,
        "real_estate_market_ready": True,
        "futures_market_ready": True,
        "options_market_ready": True,
        "volatility_market_ready": True,
        "alternative_market_ready": True,
        "certified_data_ready": True,
        "complete_screening_ready": True,
        "production_context_ready": True,
        "portfolio_construction_ready": True,
        "paper_execution_ready": True,
        "thesis_and_evaluation_ready": True,
        "daily_operations_ready": True,
        "four_screen_product_ready": True,
        "security_suite_ready": True,
        "resilience_campaign_ready": True,
        "paper_only_disclosures_ready": True,
        "paper_launch_ready": True,
        "unresolved_critical_incidents": 0,
        "data_integrity_failures": 0,
        "reconciliation_failures": 0,
        "evidence_identifiers": (
            "ci:green",
            "data-certification:approved",
            "paper-launch:approved",
        ),
        "open_development_items": ("continue next-version research on main",),
    }
    values.update(overrides)
    return ProductTestReadinessEvidence(**values)


def test_ready_baseline_does_not_require_closing_development() -> None:
    report = ProductTestReadinessEvaluator().evaluate(_evidence())

    assert report.state is ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST
    assert report.development_items == ("continue next-version research on main",)
    assert report.real_money_authorized is False
    assert report.performance_claims_permitted is False


def test_missing_sustained_launch_authority_blocks_readiness() -> None:
    report = ProductTestReadinessEvaluator().evaluate(
        _evidence(paper_launch_ready=False)
    )

    assert report.state is ProductTestReadiness.DEVELOPMENT_IN_PROGRESS
    assert "paper_launch" in report.blockers


def test_missing_market_and_data_authorities_remains_development_in_progress() -> None:
    report = ProductTestReadinessEvaluator().evaluate(
        _evidence(
            crypto_market_ready=False,
            spot_fx_market_ready=False,
            certified_data_ready=False,
            test_baseline_identifier=None,
            process_version=None,
        )
    )

    assert report.state is ProductTestReadiness.DEVELOPMENT_IN_PROGRESS
    assert set(report.blockers) >= {
        "crypto_market",
        "spot_fx_market",
        "certified_data",
        "immutable_test_baseline",
        "versioned_investment_process",
    }


def test_closed_development_with_failed_gate_is_blocked() -> None:
    report = ProductTestReadinessEvaluator().evaluate(
        _evidence(development_remains_open=False, paper_execution_ready=False)
    )

    assert report.state is ProductTestReadiness.BLOCKED
    assert "paper_execution" in report.blockers


def test_integrity_or_incident_failures_block_readiness() -> None:
    report = ProductTestReadinessEvaluator().evaluate(
        _evidence(
            unresolved_critical_incidents=1,
            data_integrity_failures=1,
            reconciliation_failures=1,
        )
    )

    assert report.state is ProductTestReadiness.DEVELOPMENT_IN_PROGRESS
    assert set(report.blockers) >= {
        "unresolved_critical_incidents",
        "data_integrity_failures",
        "reconciliation_failures",
    }


def test_readiness_history_is_append_only_and_tamper_evident(tmp_path: Path) -> None:
    store = SQLiteProductTestReadinessStore(tmp_path / "readiness.db")
    report = ProductTestReadinessEvaluator().evaluate(_evidence())

    assert store.append(report) == 1
    assert store.append(report) == 1
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE product_test_readiness_reports SET payload_json='{}' WHERE sequence=1"
            )
        connection.execute("DROP TRIGGER product_test_readiness_reports_no_update")
        connection.execute(
            "UPDATE product_test_readiness_reports SET payload_json='{}' WHERE sequence=1"
        )

    with pytest.raises(TestReadinessIntegrityError):
        store.verify_integrity()
