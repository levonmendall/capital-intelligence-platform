from __future__ import annotations

from types import SimpleNamespace

import ui_refinement


def _modules():
    calls: dict[str, list[object]] = {
        "styles": [],
        "identity": [],
        "deployment": [],
        "sidebar": [],
        "header": [],
    }

    def apply_global_style(*, dark_mode: bool = True) -> None:
        calls["styles"].append(dark_mode)

    app_impl = SimpleNamespace(
        apply_global_style=apply_global_style,
        render_sidebar=lambda: calls["sidebar"].append(True),
        render_app_header=lambda page: calls["header"].append(page),
    )
    secure_app = SimpleNamespace(
        _render_identity_controls=lambda principal: calls["identity"].append(principal),
        _render_deployment_controls=lambda principal, deployment: calls[
            "deployment"
        ].append((principal, deployment)),
    )
    return app_impl, secure_app, calls


def test_public_view_removes_technical_sidebar_and_renders_trust_strip(monkeypatch) -> None:
    app_impl, secure_app, calls = _modules()
    rendered: list[str] = []
    fake_streamlit = SimpleNamespace(session_state={}, markdown=lambda value, **_: rendered.append(value))
    monkeypatch.setattr(ui_refinement, "st", fake_streamlit)

    ui_refinement.install(app_impl, secure_app)

    public = SimpleNamespace(is_anonymous=True, is_administrator=False)
    secure_app._render_identity_controls(public)
    app_impl.apply_global_style(dark_mode=False)
    app_impl.render_sidebar()
    app_impl.render_app_header("Today")

    assert calls["identity"] == []
    assert calls["sidebar"] == []
    assert calls["styles"] == [True]
    assert any("stSidebar" in value and "display: none" in value for value in rendered)
    assert any("Public read-only viewer" in value for value in rendered)
    assert any("$250,000 paper portfolio" in value for value in rendered)
    assert any("Viewed " in value for value in rendered)


def test_authenticated_controls_remain_available_but_deployment_is_admin_only(
    monkeypatch,
) -> None:
    app_impl, secure_app, calls = _modules()
    fake_streamlit = SimpleNamespace(session_state={}, markdown=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_refinement, "st", fake_streamlit)

    ui_refinement.install(app_impl, secure_app)

    member = SimpleNamespace(is_anonymous=False, is_administrator=False)
    administrator = SimpleNamespace(is_anonymous=False, is_administrator=True)
    deployment = object()

    secure_app._render_identity_controls(member)
    secure_app._render_deployment_controls(member, deployment)
    secure_app._render_deployment_controls(administrator, deployment)

    assert calls["identity"] == [member]
    assert calls["deployment"] == [(administrator, deployment)]


def test_install_is_idempotent(monkeypatch) -> None:
    app_impl, secure_app, calls = _modules()
    fake_streamlit = SimpleNamespace(session_state={}, markdown=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_refinement, "st", fake_streamlit)

    ui_refinement.install(app_impl, secure_app)
    installed_style = app_impl.apply_global_style
    installed_identity = secure_app._render_identity_controls
    installed_deployment = secure_app._render_deployment_controls

    ui_refinement.install(app_impl, secure_app)

    assert app_impl.apply_global_style is installed_style
    assert secure_app._render_identity_controls is installed_identity
    assert secure_app._render_deployment_controls is installed_deployment
    assert calls["styles"] == []
