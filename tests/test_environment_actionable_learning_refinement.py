from __future__ import annotations

from pathlib import Path

import environment_actionable_learning_refinement as refinement


def _drivers() -> tuple[dict[str, object], ...]:
    return (
        {
            "name": "Growth",
            "value": "4.2%",
            "state": "Mixed",
            "bias": 0.0,
            "channel": "Labor demand → spending and earnings",
            "feeds": ("Equities", "Credit"),
        },
        {
            "name": "Inflation",
            "value": "3.20%",
            "state": "Elevated pressure",
            "bias": -1.0,
            "channel": "Prices → policy expectations and margins",
            "feeds": ("Bonds", "Equities", "Dollar & commodities"),
        },
        {
            "name": "Rates",
            "value": "5.25% · curve -0.40 pp",
            "state": "Inverted curve",
            "bias": -1.0,
            "channel": "Financing cost → bond prices and valuations",
            "feeds": ("Equities", "Bonds", "Dollar & commodities"),
        },
        {
            "name": "Liquidity",
            "value": "+0.05",
            "state": "Mixed",
            "bias": 0.0,
            "channel": "Funding conditions → spreads and risk appetite",
            "feeds": ("Credit", "Equities"),
        },
    )


def test_focus_driver_uses_direction_then_market_impact_priority() -> None:
    focus = refinement._focus_driver(_drivers())

    assert focus["name"] == "Inflation"
    assert focus["state"] == "Elevated pressure"


def test_watch_rows_turn_each_driver_into_a_specific_review_condition() -> None:
    rows = refinement._watch_rows(_drivers())
    by_name = {row["name"]: row for row in rows}

    assert len(rows) == 4
    assert "2–3% range" in by_name["Inflation"]["trigger"]
    assert "curve turns clearly positive" in by_name["Rates"]["trigger"]
    assert "+0.25" in by_name["Liquidity"]["trigger"]
    assert "cyclical equities" in by_name["Growth"]["impact"]


def test_learning_html_is_current_compact_and_actionable() -> None:
    html = refinement._learning_html(_drivers())

    assert "How to read today’s backdrop" in html
    assert "Signal → market channel → exposed assets" in html
    assert "Current example:" in html
    assert "What could change the backdrop" in html
    assert "Specific evidence thresholds" in html
    assert html.count('class="ci-review-card"') == 4
    assert "does not authorize a portfolio change" in html


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdown_calls: list[tuple[str, bool]] = []
        self.expander_labels: list[str] = []
        self.caption_calls: list[str] = []

    def markdown(self, body: object, *args: object, **kwargs: object) -> object:
        del args
        self.markdown_calls.append((str(body), bool(kwargs.get("unsafe_allow_html"))))
        return object()

    def expander(self, label: object, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.expander_labels.append(str(label))
        return object()

    def caption(self, body: object, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.caption_calls.append(str(body))
        return object()


def test_streamlit_proxy_replaces_only_the_dense_lower_section() -> None:
    fake = _FakeStreamlit()
    proxy = refinement._StreamlitProxy(fake, "<section>replacement</section>", "<div>note</div>")

    proxy.markdown(
        '<section><div class="ci-kicker">Investor lesson</div>'
        '<div class="ci-kicker">What would change the view</div></section>',
        unsafe_allow_html=True,
    )
    proxy.expander("Cross-asset market detail", expanded=False)
    proxy.caption("Economic readings: FRED")

    assert fake.markdown_calls == [
        ("<section>replacement</section>", True),
        ("<div>note</div>", True),
    ]
    assert fake.expander_labels == ["Explore supporting market data"]
    assert fake.caption_calls == []


def test_local_and_render_entrypoints_install_after_driver_runtime() -> None:
    for relative in ("app.py", "render_app.py"):
        source = Path(relative).read_text(encoding="utf-8")
        driver = source.index("environment_driver_education_runtime.install(")
        actionable = source.index("environment_actionable_learning_refinement.install(")
        final_owner = source.index("environment_story_placement_refinement.install(app_impl)")

        assert "import environment_actionable_learning_refinement" in source
        assert driver < actionable < final_owner
