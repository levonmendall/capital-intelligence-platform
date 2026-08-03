"""Remove indisputably dead product surfaces and their obsolete tests.

This one-use materializer is intentionally strict: every expected target must exist and
every mixed test file must contain exactly one Personal CIO-only test before mutation.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REMOVE_FILES = (
    "api/routes/objectives.py",
    "api/routes/personal.py",
    "api/routes/personal_cio_history.py",
    "personal_cio/__init__.py",
    "personal_cio/alerts.py",
    "personal_cio/brief_service.py",
    "personal_cio/brief_store.py",
    "personal_cio/models.py",
    "personal_cio/service.py",
    "personal_cio/store.py",
    "personalization/__init__.py",
    "personalization/investor_memory.py",
    "institutional_market/__init__.py",
    "institutional_market/committee_submission.py",
    "institutional_market/data_enablement.py",
    "institutional_market/review_journal.py",
    "institutional_market/score_guardrails.py",
    "institutional_market/score_v2.py",
    "institutional_market/shadow_approval.py",
    "institutional_market/walk_forward.py",
    "intelligence/report_formatter.py",
    "providers/mock_market_data.py",
    "dashboard/__init__.py",
    "dashboard/daily_intelligence.py",
    "process_lens_grid.py",
    "today_story_placement_refinement.py",
    "streamlit_paper_execution_worker.py",
    "config/crypto_venue_bindings.example.json",
    "tests/test_personal_cio.py",
    "tests/test_personal_cio_alerts.py",
    "tests/test_personal_cio_brief.py",
    "tests/test_personal_cio_api.py",
    "tests/test_committee_submission.py",
    "tests/test_production_data_enablement.py",
    "tests/test_review_journal.py",
    "tests/test_score_guardrails.py",
    "tests/test_score_v2.py",
    "tests/test_shadow_approval.py",
    "tests/test_walk_forward_calibration.py",
    "tests/test_streamlit_full_operator.py",
    "tests/test_today_story_placement_refinement.py",
)

MIXED_PERSONAL_TESTS = (
    "tests/test_business_cycle_integration.py",
    "tests/test_credit_cycle_integration.py",
    "tests/test_global_liquidity_integration.py",
    "tests/test_market_breadth_integration.py",
    "tests/test_risk_integration.py",
    "tests/test_technical_momentum_integration.py",
    "tests/test_valuation_integration.py",
)


def _remove_ast_nodes(
    path: Path,
    *,
    import_modules: set[str],
    function_names: set[str],
) -> None:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    ranges: list[tuple[int, int]] = []
    found_imports: set[str] = set()
    found_functions: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "") in import_modules:
            found_imports.add(node.module or "")
            ranges.append((node.lineno, node.end_lineno or node.lineno))
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in function_names
        ):
            found_functions.add(node.name)
            start = node.lineno
            if node.decorator_list:
                start = min(item.lineno for item in node.decorator_list)
            end = node.end_lineno or node.lineno
            while end < len(lines) and lines[end].strip() == "":
                end += 1
            ranges.append((start, end))

    missing_functions = function_names - found_functions
    if missing_functions:
        raise RuntimeError(
            f"{path.relative_to(ROOT)} is missing expected functions: "
            f"{sorted(missing_functions)}"
        )
    missing_imports = import_modules - found_imports
    if missing_imports:
        raise RuntimeError(
            f"{path.relative_to(ROOT)} is missing expected imports: "
            f"{sorted(missing_imports)}"
        )

    for start, end in sorted(ranges, reverse=True):
        del lines[start - 1 : end]
    path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    for relative in REMOVE_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"missing expected removal target: {relative}")
        path.unlink()

    for relative in MIXED_PERSONAL_TESTS:
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name.startswith("test_personal_cio_adds_")
        }
        if len(names) != 1:
            raise RuntimeError(
                f"expected one Personal CIO-only test in {relative}; found {sorted(names)}"
            )
        _remove_ast_nodes(
            path,
            import_modules={"personal_cio", "tests.test_personal_cio_brief"},
            function_names=names,
        )

    _remove_ast_nodes(
        ROOT / "tests/test_daily_intelligence_application.py",
        import_modules={"dashboard.daily_intelligence"},
        function_names={"test_daily_view_keeps_the_primary_surface_simple"},
    )

    architecture_test = ROOT / "tests/test_governing_objective_isolation.py"
    text = architecture_test.read_text(encoding="utf-8")
    old = "def test_goal_routers_are_compatibility_only() -> None:"
    new = "def test_goal_routers_are_removed_from_active_api() -> None:"
    if text.count(old) != 1:
        raise RuntimeError("governing-objective test rename target changed")
    architecture_test.write_text(text.replace(old, new), encoding="utf-8")

    archive = ROOT / "archive/REMOVED_LEGACY_CODE_2026-08-03.md"
    if archive.exists():
        raise RuntimeError(f"archive manifest already exists: {archive.relative_to(ROOT)}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(
        """# Removed legacy code — 2026-08-03

This manifest records code intentionally removed from the active repository after a
repository-wide import, runtime-entrypoint, workflow, and test-ownership audit. Git
history remains the source archive; no executable Python is retained under `archive/`.

## Removed product surfaces

- Investor-specific goals, memory, Personal CIO briefs, alerts, history, and unmounted
  API routes. The product now governs one `COMPOUNDING` paper portfolio with one
  institutional objective.
- The disconnected Institutional Market Score v2, shadow approval, score guardrails,
  parallel committee submission, and legacy walk-forward package.
- Unused dashboard, report-formatting, mock-provider, process-lens, retired Today-story
  placement, and deprecated Streamlit paper-execution compatibility modules.
- The duplicate `config/crypto_venue_bindings.example.json`; the active
  `config/crypto_venue_bindings.free.json` remains canonical.

## Preserved boundaries

This removal does not change investment thresholds, the six-specialist committee,
CIO-only authority, fail-closed evidence, independent portfolio construction,
append-only lineage, reconciled paper execution, or the prohibition on live money.

## Validation requirement

The cleanup is valid only when the complete repository validation, browser/mobile,
historical, provider, paper-readiness, and security gates pass on the cleanup branch.
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
