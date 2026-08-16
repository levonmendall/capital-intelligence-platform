from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = ROOT / "run_manual_cio_diagnostic.py"
DIAGNOSTIC_CORE = ROOT / "_manual_cio_diagnostic_core.py"


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
    # The public run_* adapter is the process entrypoint and must remain lightweight.
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


def test_manual_diagnostic_exposes_memory_telemetry_across_provider_free_phases() -> None:
    # Memory telemetry belongs to the private implementation core; the public adapter only
    # selects the governed initializer and then delegates to this unchanged implementation.
    source = DIAGNOSTIC_CORE.read_text(encoding="utf-8")
    required_phases = {
        '"process_start"',
        '"before_canonical_portfolio_initialization"',
        '"after_canonical_portfolio_initialization"',
        '"before_qualified_evidence_consumption"',
        '"before_production_context_preparation"',
        '"after_production_context_preparation"',
        '"before_worker_initialization"',
        '"after_worker_initialization"',
        '"before_paper_implementation"',
        '"after_paper_implementation"',
        '"process_finish"',
    }
    assert all(phase in source for phase in required_phases)
    assert '"before_comprehensive_discovery"' not in source
    assert '"after_comprehensive_discovery"' not in source


def test_worker_is_built_only_after_production_context_is_ready() -> None:
    # Ordering is an implementation invariant, so inspect the private implementation core.
    source = DIAGNOSTIC_CORE.read_text(encoding="utf-8")
    context_call = source.index("context = context_preparer")
    readiness_gate = source.index("if not context.ready", context_call)
    worker_load = source.index("_load_worker_dependency()", readiness_gate)
    worker_build = source.index("worker = build_worker(settings)", worker_load)
    assert context_call < readiness_gate < worker_load < worker_build


def test_importing_api_config_does_not_load_full_api_route_graph() -> None:
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            (
                "import sys; from api.config import ApiSettings; "
                "assert ApiSettings.__name__ == 'ApiSettings'; "
                "assert 'api.app' not in sys.modules; "
                "assert not any(name.startswith('api.routes.') for name in sys.modules)"
            ),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
