from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import decision_pulse_ui_refinement as refinement


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdown_values: list[str] = []
        self.caption_values: list[str] = []
        self.write_values: list[object] = []
        self.expander_labels: list[str] = []
        self.expander_expanded: list[bool] = []

    def markdown(self, value: str, **_kwargs: object) -> None:
        self.markdown_values.append(value)

    def caption(self, value: str) -> None:
        self.caption_values.append(value)

    def write(self, value: object) -> None:
        self.write_values.append(value)

    @contextmanager
    def expander(self, label: str, **kwargs: object):
        self.expander_labels.append(label)
        self.expander_expanded.append(bool(kwargs.get("expanded", False)))
        yield


DECISION_PULSE_ITEMS = (
    (
        "Market status",
        "Closed · implementation market data partial",
        "Provider-backed session and governed instrument coverage.",
    ),
    (
        "Portfolio action",
        "CIO decision: hold. No executable portfolio change is proposed.",
        "CIO state: Current · 65% confidence.",
    ),
    (
        "Portfolio effect",
        (
            "The candidate offers a 35.70% cost-adjusted expected return versus "
            "a 33.80% alternative, with -34.66% expected downside."
        ),
        "All information is interpreted through one governed portfolio.",
    ),
    (
        "What could change the decision",
        (
            "A qualified opportunity, stronger evidence, independent review, "
            "and feasible construction are required before capital can change."
        ),
        "Review trigger; not a standalone trading signal.",
    ),
)


def test_install_makes_decision_pulse_sections_individually_expandable(
    monkeypatch,
) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    style_calls: list[bool] = []
    delegated_calls: list[tuple[object, str]] = []
    app_impl = SimpleNamespace(
        apply_global_style=lambda *, dark_mode=True: style_calls.append(dark_mode),
        status_list=lambda items, *, variant="history": delegated_calls.append(
            (items, variant)
        ),
    )

    refinement.install(app_impl)
    installed_status_list = app_impl.status_list
    refinement.install(app_impl)

    assert app_impl.status_list is installed_status_list

    app_impl.apply_global_style(dark_mode=False)
    app_impl.status_list(DECISION_PULSE_ITEMS, variant="today")

    assert style_calls == [False]
    assert delegated_calls == []
    assert fake_streamlit.expander_expanded == [False] * 4
    section_names = [label.split(" · ", 1)[0] for label in fake_streamlit.expander_labels]
    assert section_names == [
        "MARKET STATUS",
        "PORTFOLIO ACTION",
        "PORTFOLIO EFFECT",
        "WHAT COULD CHANGE THE DECISION",
    ]
    assert not any(
        label.startswith("Explore ")
        for label in fake_streamlit.expander_labels
    )
    assert fake_streamlit.write_values == [item[1] for item in DECISION_PULSE_ITEMS]
    assert fake_streamlit.caption_values == [item[2] for item in DECISION_PULSE_ITEMS]

    markup = "\n".join(fake_streamlit.markdown_values)
    assert ':has(.decision-pulse-marker)' in markup
    for marker in (
        "decision-section-market",
        "decision-section-action",
        "decision-section-portfolio",
        "decision-section-change",
    ):
        assert marker in markup


def test_install_preserves_unrelated_status_lists(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    delegated_calls: list[tuple[object, str]] = []
    app_impl = SimpleNamespace(
        apply_global_style=lambda *, dark_mode=True: None,
        status_list=lambda items, *, variant="history": delegated_calls.append(
            (items, variant)
        ),
    )
    refinement.install(app_impl)

    unrelated = (("Report state", "Current", "Governed history"),)
    app_impl.status_list(unrelated, variant="history")

    assert delegated_calls == [(unrelated, "history")]
    assert fake_streamlit.expander_labels == []
