from __future__ import annotations

import json
from pathlib import Path

from cio.growth_ensemble import GrowthEnsemblePolicy, GrowthStage
from opportunity.models import AnalysisLane


def test_growth_lanes_are_explicit() -> None:
    assert AnalysisLane.PARTICIPATION.value == "participation"
    assert AnalysisLane.EXPLORATION.value == "exploration"


def test_progressive_growth_policy_has_nonzero_small_entry_path() -> None:
    policy = GrowthEnsemblePolicy()
    assert 0.0 < policy.exploration_floor <= policy.maximum_exploration_weight
    assert policy.maximum_exploration_weight <= 0.01
    assert policy.validation_floor < policy.qualified_floor
    assert GrowthStage.STRATEGIC.value == "strategic"


def test_pilot_defaults_to_participation_not_cash() -> None:
    payload = json.loads(
        Path("config/free_paper_pilot_universe.json").read_text(encoding="utf-8")
    )
    assert payload["minimum_cash_weight"] == 0.05
    assert payload["maximum_batch_turnover"] == 0.20
    assert "compounded growth" in payload["objective"].lower()


def test_discovery_failure_cannot_be_reported_as_no_opportunity() -> None:
    source = Path("production_context_publication_governed.py").read_text(
        encoding="utf-8"
    )
    assert "Complete opportunity search is unavailable" in source
    assert "conclusion is prohibited until broad U.S.-equity discovery completes" in source


def test_cio_uses_ensemble_and_progressive_lanes() -> None:
    source = Path("cio/service.py").read_text(encoding="utf-8")
    assert "AdaptiveRobustGrowthEnsemble" in source
    assert 'progressive_lane = str(analysis_lane).lower()' in source
    assert "ensemble.minimum_target_weight" in source
    assert "effective_position_multiplier" in source
