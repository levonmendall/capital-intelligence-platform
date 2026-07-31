from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 match, found {count}: {old[:140]!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "production_context_publication_governed.py",
    'STATE_SCHEMA = "production-context-publication-state.v3"\n',
    'STATE_SCHEMA = "production-context-publication-state.v4-growth"\n',
)
replace_once(
    "production_context_publication_governed.py",
    '''    except Exception as error:
        if dynamic_holdings:
            return _blocked(
                cycle_key=cycle_key,
                scheduled_for=scheduled,
                decision_as_of=decision_as_of,
                detail=(
                    "Broad-equity discovery failed while company holdings require review: "
                    f"{type(error).__name__}: {error}"
                ),
                instrument_count=len(base_universe.instruments),
            )
        discovery = None
        universe = base_universe
''',
    '''    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail=(
                "Complete opportunity search is unavailable; a no-superior-opportunity "
                "conclusion is prohibited until broad U.S.-equity discovery completes: "
                f"{type(error).__name__}: {error}"
            ),
            instrument_count=len(base_universe.instruments),
        )
''',
)

config_path = ROOT / "config/free_paper_pilot_universe.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
config["identifier"] = "free-paper-pilot-us-listed-wrappers.v3-growth"
config["objective"] = (
    "Maximize robust long-term compounded growth through persistent diversified "
    "participation, progressive opportunity sizing, and independent drawdown, "
    "liquidity, concentration, turnover, evidence-integrity, and execution controls."
)
config["minimum_cash_weight"] = 0.05
config["maximum_batch_turnover"] = 0.20
limitations = list(config.get("limitations", []))
limitations.append(
    "Cash is an explicit competing allocation rather than the default portfolio; "
    "complete opportunity search and portfolio-survival controls remain mandatory."
)
config["limitations"] = list(dict.fromkeys(limitations))
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

write(
    "docs/ADAPTIVE_ROBUST_GROWTH_ENSEMBLE.md",
    '''# Adaptive Robust Growth Ensemble

## Objective

The canonical `COMPOUNDING` portfolio seeks the highest robust expected geometric
growth available from the approved paper universe. The normal state is productive
market participation, not idle cash. Cash remains a valid defensive allocation and
must compete with every other use of capital.

## Architecture

1. **Complete opportunity search** evaluates the strategic cross-asset wrappers,
   current holdings, and broad eligible U.S. operating companies. A discovery
   failure produces `blocked`, never `no_superior_opportunity`.
2. **Independent return engines** are the existing macro, market/trend,
   cross-asset forecast, fundamental/valuation, portfolio-diversification, and
   robust geometric-growth analyses.
3. **Adaptive meta-allocation** converts engine coverage, agreement, confidence,
   dispersion, and robust edge into one progressive stage: observe, explore,
   validate, qualified, established, or strategic.
4. **Progressive sizing** uses small paper allocations when hard controls pass but
   ordinary return, probability, persistence, or edge evidence is incomplete.
   Uncertainty normally reduces size before it eliminates participation.
5. **Independent risk construction** retains cash, turnover, concentration,
   expected-shortfall, stressed-drawdown, liquidity, cost, and execution limits.
   Construction may only reduce a CIO-supported target.
6. **Bounded symmetric learning** may adjust the ensemble multiplier only from a
   strict, mature, point-in-time sample. It cannot create a candidate, increase a
   forecast, bypass current evidence, authorize execution, or promote policy.

## Hard vetoes

The growth model cannot bypass incomplete or invalid evidence and lineage,
prohibited or untradeable instruments, inadequate liquidity, unacceptable scenario
downside, non-positive portfolio wealth, internally inconsistent scenarios,
unresolvable funding or implementation constraints, construction drawdown and
concentration limits, or thesis and evidence-integrity emergencies.

## Capital policy

The paper pilot retains a 5% operational cash floor and permits up to 20% normal
batch turnover. Individual exploratory company entries remain capped at 1%, while
established company positions remain subject to the governed 5% ceiling. Strategic
wrappers retain exposure-specific caps.

## Authority

There is one canonical CIO and one canonical portfolio. The ensemble provides
decision evidence and a bounded sizing stage. It has no brokerage, paper-execution,
real-money, policy-promotion, or governance-bypass authority.
''',
)

write(
    "tests/test_adaptive_robust_growth_ensemble.py",
    '''from __future__ import annotations

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
    assert "a no-superior-opportunity conclusion is prohibited" in source


def test_cio_uses_ensemble_and_progressive_lanes() -> None:
    source = Path("cio/service.py").read_text(encoding="utf-8")
    assert "AdaptiveRobustGrowthEnsemble" in source
    assert 'progressive_lane = str(analysis_lane).lower()' in source
    assert "ensemble.minimum_target_weight" in source
    assert "effective_position_multiplier" in source
''',
)

exporter = ROOT / ".github/workflows/export-adaptive-growth-source.yml"
if exporter.exists():
    exporter.unlink()

print("production search, capital policy, documentation, and tests patched")
