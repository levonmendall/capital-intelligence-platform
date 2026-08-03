"""Prevent retired architectures from silently returning to the active tree."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RETIRED_PATHS = (
    "api/routes/objectives.py",
    "api/routes/personal.py",
    "api/routes/personal_cio_history.py",
    "personal_cio",
    "personalization",
    "institutional_market",
    "dashboard",
    "intelligence/cio.py",
    "intelligence/decision_discipline.py",
    "intelligence/engine_cycle.py",
    "intelligence/forecast.py",
    "intelligence/forecast_engine.py",
    "intelligence/forecast_strategy.py",
    "intelligence/liquidity_cycle.py",
    "intelligence/observation.py",
    "intelligence/observation_adapter.py",
    "intelligence/portfolio_manager.py",
    "intelligence/rebalancer.py",
    "intelligence/recommendation_builder.py",
    "intelligence/recommendation_engine.py",
    "intelligence/recommendation_rules.py",
    "intelligence/report_formatter.py",
    "intelligence/state.py",
    "intelligence/state_engine.py",
    "intelligence/strategies",
    "intelligence/theme.py",
    "intelligence/theme_engine.py",
    "intelligence/thesis.py",
    "intelligence/thesis_engine.py",
    "providers/mock_market_data.py",
    "process_lens_grid.py",
    "today_story_placement_refinement.py",
    "streamlit_paper_execution_worker.py",
    "config/crypto_venue_bindings.example.json",
)

RETIRED_MODULE_PREFIXES = (
    "api.routes.objectives",
    "api.routes.personal",
    "api.routes.personal_cio_history",
    "dashboard",
    "institutional_market",
    "personal_cio",
    "personalization",
    "intelligence.cio",
    "intelligence.decision_discipline",
    "intelligence.engine_cycle",
    "intelligence.forecast",
    "intelligence.forecast_engine",
    "intelligence.forecast_strategy",
    "intelligence.liquidity_cycle",
    "intelligence.observation",
    "intelligence.observation_adapter",
    "intelligence.portfolio_manager",
    "intelligence.rebalancer",
    "intelligence.recommendation_builder",
    "intelligence.recommendation_engine",
    "intelligence.recommendation_rules",
    "intelligence.report_formatter",
    "intelligence.state",
    "intelligence.state_engine",
    "intelligence.strategies",
    "intelligence.theme",
    "intelligence.theme_engine",
    "intelligence.thesis",
    "intelligence.thesis_engine",
    "providers.mock_market_data",
    "process_lens_grid",
    "streamlit_paper_execution_worker",
    "today_story_placement_refinement",
)


def _is_retired_module(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in RETIRED_MODULE_PREFIXES
    )


def test_retired_paths_remain_absent() -> None:
    restored = [relative for relative in RETIRED_PATHS if (ROOT / relative).exists()]
    assert not restored, f"retired code was restored without governance: {restored}"
    assert (ROOT / "config/crypto_venue_bindings.free.json").is_file()


def test_active_python_does_not_import_retired_modules() -> None:
    violations: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if _is_retired_module(module):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} imports {module}"
                    )
    assert not violations, "retired imports found:\n" + "\n".join(violations)


def test_canonical_authority_modules_remain_present() -> None:
    required = (
        "application/cio_cycle.py",
        "application/production_context.py",
        "application/production_context_runtime.py",
        "cio/service.py",
        "committee/specialists.py",
        "opportunity/engine.py",
        "portfolio/construction_api.py",
        "paper_execution_runtime.py",
        "run_autonomous_paper_operator.py",
        "render_app.py",
        "api/app.py",
    )
    missing = [relative for relative in required if not (ROOT / relative).is_file()]
    assert not missing, f"canonical authority modules are missing: {missing}"
