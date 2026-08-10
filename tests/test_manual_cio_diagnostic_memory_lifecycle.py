from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = ROOT / "run_manual_cio_diagnostic.py"


def _top_level_import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_manual_diagnostic_keeps_heavy_application_imports_out_of_process_startup() -> None:
    roots = _top_level_import_roots(DIAGNOSTIC)
    forbidden = {
        "api",
        "cio_pending_transactions",
        "operations",
        "paper_execution_runtime",
        "portfolio",
        "production_context_publication_runtime",
        "production_context_state_resilience",
        "public_live_collection_runtime",
        "run_autonomous_paper_operator",
        "run_scheduler",
    }
    assert roots.isdisjoint(forbidden)


def test_manual_diagnostic_exposes_memory_telemetry_across_critical_phases() -> None:
    source = DIAGNOSTIC.read_text(encoding="utf-8")
    required_phases = {
        '"process_start"',
        '"before_canonical_portfolio_initialization"',
        '"after_canonical_portfolio_initialization"',
        '"before_comprehensive_discovery"',
        '"after_comprehensive_discovery"',
        '"before_worker_initialization"',
    }
    assert all(phase in source for phase in required_phases)


def test_worker_is_built_only_after_production_context_is_ready() -> None:
    source = DIAGNOSTIC.read_text(encoding="utf-8")
    context_call = source.index("context = context_preparer")
    readiness_gate = source.index("if not context.ready", context_call)
    worker_load = source.index("_load_worker_dependency()", readiness_gate)
    worker_build = source.index("worker = build_worker(settings)", worker_load)
    assert context_call < readiness_gate < worker_load < worker_build
