"""Remove retired analytical wrapper orchestration while preserving active engines/APIs."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REMOVE_FILES = (
    "intelligence/engine_cycle.py",
    "intelligence/liquidity_cycle.py",
)

TEST_MUTATIONS = {
    "tests/test_business_cycle_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor"},
        "functions": {
            "test_multi_engine_cycle_persists_results_without_changing_canonical_result"
        },
    },
    "tests/test_credit_cycle_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor"},
        "functions": {
            "test_multi_engine_cycle_persists_three_results_without_changing_contract"
        },
    },
    "tests/test_global_liquidity_integration.py": {
        "imports": {"intelligence.liquidity_cycle"},
        "classes": {"_CanonicalExecutor"},
        "functions": {
            "test_cycle_wrapper_persists_liquidity_without_changing_canonical_result"
        },
    },
    "tests/test_market_breadth_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor"},
        "functions": {
            "test_multi_engine_cycle_persists_four_results_without_changing_contract"
        },
    },
    "tests/test_risk_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor"},
        "functions": {
            "test_multi_engine_cycle_persists_seven_results_without_changing_contract"
        },
    },
    "tests/test_technical_momentum_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor"},
        "functions": {
            "test_multi_engine_cycle_persists_six_results_without_changing_contract"
        },
    },
    "tests/test_valuation_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor"},
        "functions": {
            "test_multi_engine_cycle_persists_five_results_without_changing_contract"
        },
    },
    "tests/test_multi_engine_governance_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor", "_Engine"},
        "functions": {
            "test_cycle_persists_governance_without_changing_canonical_contract",
            "test_governance_requires_synthesis_dependencies",
        },
    },
    "tests/test_multi_engine_normalization_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor", "_Engine"},
        "functions": {
            "test_cycle_persists_raw_results_and_normalization_without_changing_contract",
            "test_cycle_requires_normalizer_and_store_together",
        },
    },
    "tests/test_multi_engine_synthesis_integration.py": {
        "imports": {"intelligence.engine_cycle"},
        "classes": {"_CanonicalExecutor", "_Engine"},
        "functions": {
            "test_cycle_persists_synthesis_without_changing_canonical_contract"
        },
    },
}

EXPORT_BLOCKS = (
    '''    "AnalyticalEngineCycleExecutor": (
        "intelligence.engine_cycle",
        "AnalyticalEngineCycleExecutor",
    ),
''',
    '''    "LiquidityAwareCycleExecutor": (
        "intelligence.liquidity_cycle",
        "LiquidityAwareCycleExecutor",
    ),
''',
)


def _remove_nodes(path: Path, mutation: dict[str, set[str]]) -> None:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    ranges: list[tuple[int, int]] = []
    found_imports: set[str] = set()
    found_classes: set[str] = set()
    found_functions: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "") in mutation["imports"]:
            found_imports.add(node.module or "")
            ranges.append((node.lineno, node.end_lineno or node.lineno))
            continue
        if isinstance(node, ast.ClassDef) and node.name in mutation["classes"]:
            found_classes.add(node.name)
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            end = node.end_lineno or node.lineno
            while end < len(lines) and not lines[end].strip():
                end += 1
            ranges.append((start, end))
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in mutation["functions"]:
            found_functions.add(node.name)
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            end = node.end_lineno or node.lineno
            while end < len(lines) and not lines[end].strip():
                end += 1
            ranges.append((start, end))

    if found_imports != mutation["imports"]:
        raise RuntimeError(f"{path}: expected imports changed: {found_imports}")
    if found_classes != mutation["classes"]:
        raise RuntimeError(f"{path}: expected classes changed: {found_classes}")
    if found_functions != mutation["functions"]:
        raise RuntimeError(f"{path}: expected functions changed: {found_functions}")

    for start, end in sorted(ranges, reverse=True):
        del lines[start - 1 : end]
    path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    for relative in REMOVE_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"missing expected removal target: {relative}")
        path.unlink()

    for relative, mutation in TEST_MUTATIONS.items():
        _remove_nodes(ROOT / relative, mutation)

    init_path = ROOT / "intelligence/__init__.py"
    text = init_path.read_text(encoding="utf-8")
    for block in EXPORT_BLOCKS:
        if text.count(block) != 1:
            raise RuntimeError("analytical wrapper export block changed")
        text = text.replace(block, "")
    init_path.write_text(text, encoding="utf-8")

    doc_path = ROOT / "docs/BUSINESS_CYCLE_ENGINE.md"
    doc = doc_path.read_text(encoding="utf-8")
    start = doc.index("## Personal CIO integration")
    end = doc.index("## API")
    replacement = '''## Committee and CIO use

The business-cycle result is persisted as point-in-time analytical evidence and is
available to the existing specialist and CIO process. It cannot independently create,
size, authorize, construct, or execute an investment action.

## Scheduling and persistence

Current production scheduling is owned by the canonical headless operating path. The
retired `LiquidityAwareCycleExecutor` and `AnalyticalEngineCycleExecutor` wrappers are
not part of the supported runtime and have been removed. Individual analytical engines,
their append-only stores, read-only API routes, and governed normalization, synthesis,
and evidence-governance records remain supported.

The analytical engine database remains included in encrypted backups, exposed as an
optional readiness component, and protected by append-only update and delete triggers.

'''
    doc_path.write_text(doc[:start] + replacement + doc[end:], encoding="utf-8")

    manifest = ROOT / "archive/REMOVED_LEGACY_ANALYTICAL_ORCHESTRATION_2026-08-03.md"
    if manifest.exists():
        raise RuntimeError("analytical orchestration removal manifest already exists")
    manifest.write_text(
        """# Removed legacy analytical orchestration — 2026-08-03

The retired `AnalyticalEngineCycleExecutor` and `LiquidityAwareCycleExecutor` wrappers
were removed after confirming that supported production scheduling uses the canonical
headless CIO operating path instead.

Individual macro, valuation, breadth, momentum, risk, credit, and liquidity engines
remain available through their append-only stores and read-only APIs. Normalization,
synthesis, and governance records remain supported. Tests that exclusively exercised
the removed wrappers were deleted from mixed integration files; active API tests were
preserved.

Git history is the source archive. No investment or execution authority changed.
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
