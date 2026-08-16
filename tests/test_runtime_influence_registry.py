from __future__ import annotations

from pathlib import Path

from governance.runtime_influence_registry import (
    ComponentLifecycle,
    audit_repository,
    build_import_graph,
    classify_module,
    discover_modules,
)


ROOT = Path(__file__).resolve().parents[1]


def test_repository_capability_contracts_are_valid() -> None:
    audit = audit_repository(ROOT)

    assert audit.passed, "\n".join(audit.violations)
    assert audit.module_count > 0
    assert audit.reachable_module_count > 0
    assert "run_autonomous_paper_operator" in audit.runtime_roots
    assert "run_render_service" in audit.runtime_roots


def test_every_production_python_module_receives_a_lifecycle() -> None:
    audit = audit_repository(ROOT)

    assert len(audit.modules) == audit.module_count
    assert all(isinstance(item.lifecycle, ComponentLifecycle) for item in audit.modules)
    assert not any(not item.module.strip() for item in audit.modules)


def test_static_import_graph_finds_runtime_reachability(tmp_path: Path) -> None:
    (tmp_path / "run_worker.py").write_text(
        "from package.consumer import run\nrun()\n",
        encoding="utf-8",
    )
    package = tmp_path / "package"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "consumer.py").write_text(
        "from package import producer\n\ndef run():\n    return producer.VALUE\n",
        encoding="utf-8",
    )
    (package / "producer.py").write_text("VALUE = 1\n", encoding="utf-8")

    modules = discover_modules(tmp_path)
    graph = build_import_graph(tmp_path, modules)

    assert "package.consumer" in graph["run_worker"]
    assert "package.producer" in graph["package.consumer"]


def test_unreachable_decision_module_is_classified_orphaned(tmp_path: Path) -> None:
    package = tmp_path / "intelligence"
    package.mkdir()
    path = package / "unused.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")

    lifecycle = classify_module(
        "intelligence.unused",
        path,
        reachable=False,
    )

    assert lifecycle is ComponentLifecycle.ORPHANED
