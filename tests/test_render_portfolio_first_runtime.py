from __future__ import annotations

from types import SimpleNamespace

import app_impl
import portfolio_first_ui_refinement
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


def test_render_portfolio_bridge_enforces_capital_report_remaining_order(
    monkeypatch,
) -> None:
    events: list[str] = []
    mandate = {
        "nav": 250_000.0,
        "cash": 250_000.0,
        "holdings": [],
        "total_pnl": 0.0,
        "total_return": 0.0,
    }
    construction = {"status": "no_change", "trades": []}
    briefing = {"portfolio_decision": "Hold current capital position."}
    principal = object()

    def old_portfolio_renderer(
        dependencies: object,
        *,
        principal: object | None,
    ) -> None:
        del dependencies, principal

    def fragment_renderer(
        dependencies: object,
        *,
        principal: object | None,
    ) -> None:
        del dependencies, principal

    fragment_renderer.__wrapped__ = old_portfolio_renderer  # type: ignore[attr-defined]

    class Dependencies:
        def get_mandate_details(self, portfolio_code: str):
            assert portfolio_code == app_impl.CANONICAL_PORTFOLIO_CODE
            return mandate

    def latest(event_type: str):
        if event_type == "portfolio_construction":
            return construction
        if event_type == "daily_cio_briefing":
            return briefing
        raise AssertionError(f"unexpected event type: {event_type}")

    monkeypatch.setattr(app_impl, "_latest", latest)
    monkeypatch.setattr(
        render_app.st,
        "markdown",
        lambda content, *, unsafe_allow_html=False: events.append("style"),
    )

    def capital_structure(app: object, *, mandate: object):
        del app
        assert mandate is not None
        events.append("capital")
        return 250_000.0, 250_000.0, 0.0

    def cio_report(
        app: object,
        *,
        briefing: object,
        construction: object,
        mandate: object,
        deployed: float,
    ) -> None:
        del app
        assert briefing is not None
        assert construction is not None
        assert mandate is not None
        assert deployed == 0.0
        events.append("report")

    def remaining_portfolio(
        app: object,
        original: object,
        dependencies: object,
        *,
        principal: object | None,
    ) -> None:
        del app
        assert original is old_portfolio_renderer
        assert isinstance(dependencies, Dependencies)
        assert principal is not None
        events.append("remaining")

    monkeypatch.setattr(
        portfolio_first_ui_refinement,
        "_capital_structure",
        capital_structure,
    )
    monkeypatch.setattr(
        portfolio_first_ui_refinement,
        "_render_cio_report",
        cio_report,
    )
    monkeypatch.setattr(
        portfolio_first_ui_refinement,
        "_render_remaining_portfolio",
        remaining_portfolio,
    )

    renderer = render_app._portfolio_first_sync_renderer(fragment_renderer)
    renderer(Dependencies(), principal=principal)

    assert events == ["style", "capital", "report", "remaining"]


def test_render_entrypoint_registers_portfolio_first_sync_target() -> None:
    source = __import__("pathlib").Path("render_app.py").read_text(encoding="utf-8")

    portfolio_branch = source.index('attribute_name == "_render_portfolio"')
    target_registration = source.index(
        "_portfolio_first_sync_renderer(renderer)",
        portfolio_branch,
    )
    guard_installation = source.index("guarded = _guarded_renderer", target_registration)

    assert portfolio_branch < target_registration < guard_installation
