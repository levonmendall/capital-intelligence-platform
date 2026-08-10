from __future__ import annotations

from pathlib import Path

import render_app


def test_explicit_render_target_takes_precedence_over_fragment_unwrap() -> None:
    def fragment_renderer() -> None:
        return None

    def old_renderer() -> None:
        return None

    def explicit_renderer() -> None:
        return None

    fragment_renderer.__wrapped__ = old_renderer  # type: ignore[attr-defined]
    setattr(
        fragment_renderer,
        render_app._RENDER_SYNC_TARGET_ATTRIBUTE,
        explicit_renderer,
    )

    assert render_app._synchronous_renderer(fragment_renderer) is explicit_renderer


def test_render_runtime_preserves_canonical_portfolio_renderer_without_bridge() -> None:
    source = Path("render_app.py").read_text(encoding="utf-8")
    main_source = source[source.index("def main() -> None:") :]
    install_call = "portfolio_ui_refinement.install(app_impl)"
    prepare_call = "prepare_render_surface_runtime()"

    assert install_call in main_source
    assert main_source.index(install_call) < main_source.index(prepare_call)
    assert "_portfolio_first_sync_renderer" not in source
    assert "portfolio_first_ui_refinement" not in source


def test_render_surface_guard_wraps_portfolio_without_rebinding_its_content_owner() -> None:
    source = Path("render_app.py").read_text(encoding="utf-8")
    runtime_source = source[
        source.index("def prepare_render_surface_runtime() -> None:") :
        source.index("def deployment_context_from_environment()")
    ]

    assert "for attribute_name in _RENDER_SURFACE_NAMES" in runtime_source
    assert "renderer = getattr(app_impl, attribute_name)" in runtime_source
    assert "guarded = _guarded_renderer" in runtime_source
    assert "setattr(app_impl, attribute_name, guarded)" in runtime_source
    assert 'attribute_name == "_render_portfolio"' not in runtime_source
