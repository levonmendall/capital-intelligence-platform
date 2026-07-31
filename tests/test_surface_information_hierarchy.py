# Compact hierarchy contract for the four governed operating surfaces.

from pathlib import Path


def _function_block(source: str, name: str, next_name: str | None) -> str:
    start = source.index(f"def {name}() -> None:")
    end = (
        len(source)
        if next_name is None
        else source.index(f"def {next_name}() -> None:", start)
    )
    return source[start:end]


def test_every_surface_leads_with_a_compact_plain_language_synopsis() -> None:
    source = Path("app_impl.py").read_text(encoding="utf-8")
    expectations = (
        (
            "_render_today",
            "_render_environment",
            "Decision pulse",
            "How the Today surface works",
        ),
        (
            "_render_environment",
            "_render_portfolio",
            "Market atmosphere",
            "How the Environment surface works",
        ),
        (
            "_render_portfolio",
            "_render_history",
            "Portfolio posture",
            "How the Portfolio surface works",
        ),
        (
            "_render_history",
            None,
            "History synopsis",
            "How the History surface works",
        ),
    )
    for name, next_name, synopsis, process_label in expectations:
        block = _function_block(source, name, next_name)
        assert synopsis in block
        assert process_label in block
        assert block.index(synopsis) < block.index(process_label)


def test_today_answers_the_five_user_questions_visibly() -> None:
    app_source = Path("app_impl.py").read_text(encoding="utf-8")
    presenter_source = Path("concise_operating_intelligence_ui.py").read_text(
        encoding="utf-8"
    )
    ui_source = Path("premium_ui.py").read_text(encoding="utf-8")
    block = _function_block(app_source, "_render_today", "_render_environment")
    assert "TODAY_MARKET_BRIEF" in block
    assert "Investment world today" in presenter_source
    for label in (
        "What changed",
        "Why investors care",
        "Portfolio effect",
        "CIO response",
        "What to watch next",
    ):
        assert label in ui_source
    for label in (
        "Market status",
        "Portfolio action",
        "Portfolio effect",
        "What could change the decision",
    ):
        assert label in block


def test_environment_portfolio_and_history_communicate_current_state() -> None:
    source = Path("app_impl.py").read_text(encoding="utf-8")
    for phrase in (
        "The current economic and cross-asset setting",
        "Portfolio implication",
        "CIO response",
        "Where capital sits, why it is positioned there",
        "Why capital is positioned this way",
        "Implementation state",
        "Outcome status",
    ):
        assert phrase in source


def test_operational_detail_follows_surface_synopses() -> None:
    entrypoint = Path("app.py").read_text(encoding="utf-8")
    implementation = Path("app_impl.py").read_text(encoding="utf-8")
    for marker in (
        "TODAY_MARKET_BRIEF",
        "TODAY_OPPORTUNITY_SCAN",
        "ENVIRONMENT_ECONOMIC_BRIEF",
        "PORTFOLIO_INFORMATION_FRESHNESS",
        "LIVE_TODAY_OPERATING_CONTEXT",
        "LIVE_ENVIRONMENT_MARKET_TABLE",
        "PAPER_DECISION_CONTROLS",
        "LIVE_PORTFOLIO_MARKS",
        "OPERATING_REPORT_HISTORY",
        "CIO_REPORT_ARCHIVE",
    ):
        assert marker in entrypoint or marker in implementation
    assert "Administrator operations" in entrypoint
    assert "Production smoke test" in entrypoint
    assert "paper decision approval insertion point is unavailable" in entrypoint
    navigation = entrypoint[
        entrypoint.index("def _render_navigation_with_admin_control") :
    ]
    navigation = navigation[: navigation.index("def _compatible_metric_grid")]
    assert "Production smoke test" not in navigation


def test_decision_change_details_are_collapsed_by_default() -> None:
    implementation = Path("app_impl.py").read_text(encoding="utf-8")
    entrypoint = Path("app.py").read_text(encoding="utf-8")
    assert 'with st.expander("Decision evidence and audit reference", expanded=False):' in implementation
    assert 'with st.expander("What could change the assessment", expanded=False):' in implementation
    assert 'with st.expander("Live operating context", expanded=False):' in entrypoint
    assert 'with st.expander("Cross-asset market detail", expanded=False):' in entrypoint
    assert 'with st.expander("Paper implementation and controls", expanded=False):' in entrypoint
    assert "brittle replacements of complete visual blocks" in entrypoint


def test_mobile_hero_is_compact_and_direct() -> None:
    source = Path("premium_ui.py").read_text(encoding="utf-8")
    assert "Today's capital briefing" in source
    assert "Today's market environment" in source
    assert "Current portfolio position" in source
    assert "Decisions, actions and learning" in source
    assert ".compact-surface-head h1{font-size:1.82rem" in source
    assert ".hero-shell{display:none}" in source


def test_paper_implementation_uses_plain_language() -> None:
    source = Path("cio_pending_transactions_ui.py").read_text(encoding="utf-8")
    assert 'st.subheader("Paper implementation status")' in source
    assert "How the latest CIO conclusion translates" in source
    assert "CIO Pending Transaction Recommendations" not in source
