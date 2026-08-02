"""Shared test configuration."""

from dataclasses import replace
from pathlib import Path
import sys

import pytest

import core.database as database
from committee.specialists import AssetValuationSpecialistContext
from core.seed import seed_mandates


@pytest.fixture(autouse=True)
def isolated_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Create and seed a temporary database for every test."""

    database_path = tmp_path / "capital_intelligence_test.db"

    monkeypatch.setattr(
        database,
        "DATABASE_FILE",
        database_path,
    )

    database.initialize_database()
    seed_mandates()

    yield database_path


@pytest.fixture(autouse=True)
def certified_adapter_asset_valuation(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
):
    """Give certified ETF production fixtures their required valuation packet."""

    adapter_module = sys.modules.get(
        "tests.test_canonical_production_context_adapter"
    )
    target_module = None

    if request.module.__name__ == "tests.test_production_context_assembly":
        target_module = request.module
    elif adapter_module is not None:
        adapter = getattr(adapter_module, "_adapter", None)
        uses_adapter = (
            request.module is adapter_module
            or (
                adapter is not None
                and getattr(request.module, "_adapter", None) is adapter
            )
        )
        if uses_adapter:
            target_module = adapter_module

    if target_module is None:
        yield
        return

    original = target_module._candidate_evidence

    def candidate_evidence_with_asset_valuation(candidate):
        evidence = original(candidate)
        return replace(
            evidence,
            asset_valuation=AssetValuationSpecialistContext(
                as_of=target_module.AS_OF,
                asset_class=candidate.instrument.asset_class,
                expected_return_impact=0.02,
                confidence=0.90,
                valuation_evidence=(
                    "Certified ETF look-through valuation supports the candidate",
                ),
                contradictory_evidence=(
                    "Underlying index valuation can contract before fundamentals change",
                ),
                critical_assumptions=(
                    "The ETF continues to track its certified underlying exposure",
                ),
                risks=(
                    "Broad-market valuation multiples may compress",
                ),
                limitations=(
                    "ETF valuation is derived from the underlying index exposure",
                ),
                change_conditions=(
                    "Reassess after a material change in index composition or valuation",
                ),
                evidence_identifiers=(
                    "evidence:fundamental:spy",
                ),
            ),
        )

    monkeypatch.setattr(
        target_module,
        "_candidate_evidence",
        candidate_evidence_with_asset_valuation,
    )
    yield
