from __future__ import annotations

import ast
from pathlib import Path

import run_manual_cio_diagnostic as diagnostic
from portfolio.initialization import (
    CanonicalPortfolioInitializationError,
    ensure_canonical_portfolio_store as governed_initializer,
)
from portfolio.state import SQLiteCanonicalPortfolioStore


def test_manual_cio_diagnostic_binds_governed_initializer(monkeypatch) -> None:
    monkeypatch.setattr(diagnostic, "ensure_canonical_portfolio_store", None)

    diagnostic._load_canonical_dependency()

    assert diagnostic.ensure_canonical_portfolio_store is governed_initializer


def test_manual_cio_governed_initializer_preserves_genesis_marker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostic, "ensure_canonical_portfolio_store", None)
    diagnostic._load_canonical_dependency()
    path = tmp_path / "canonical_portfolio.db"

    first = diagnostic.ensure_canonical_portfolio_store(path)
    assert first.created is True
    assert SQLiteCanonicalPortfolioStore(path).latest() is not None

    marker = path.with_name(path.name + ".canonical-init.lock")
    assert marker.exists()
    path.unlink()

    try:
        diagnostic.ensure_canonical_portfolio_store(path)
    except CanonicalPortfolioInitializationError as error:
        assert error.failure_type == "missing_snapshot"
    else:  # pragma: no cover - the production invariant must fail closed.
        raise AssertionError("missing canonical history was silently recreated")

    assert marker.exists()
    assert not path.exists()


def test_production_modules_cannot_import_legacy_portfolio_initializer() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    excluded_roots = {"tests", ".venv", "venv"}

    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in excluded_roots:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "portfolio.state":
                continue
            if any(alias.name == "ensure_canonical_portfolio_store" for alias in node.names):
                offenders.append(str(relative))

    assert offenders == [], (
        "production code must use portfolio.initialization.ensure_canonical_portfolio_store; "
        f"legacy reset-capable imports found in {sorted(offenders)}"
    )
