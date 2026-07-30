from pathlib import Path


def _function_block(source: str, name: str, next_name: str | None) -> str:
    start = source.index(f"def {name}() -> None:")
    end = (
        len(source)
        if next_name is None
        else source.index(f"def {next_name}() -> None:", start)
    )
    return source[start:end]


def test_every_surface_leads_with_a_plain_language_synopsis() -> None:
    source = Path("app_impl.py").read_text(encoding="utf-8")
    expectations = (
        (
            "_render_today",
            "_render_environment",
            "Today's CIO briefing",
            "How the Today surface works",
        ),
        (
            "_render_environment",
            "_render_portfolio",
            "Environment synopsis",
            "How the Environment surface works",
        ),
        (
            "_render_portfolio",
            "_render_history",
            "Portfolio synopsis",
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
    source = Path("app_impl.py").read_text(encoding="utf-8")
    block = _function_block(source, "_render_today", "_render_environment")
    for label in (
        "What deserves attention",
        "What changed",
        "Why it matters to the portfolio",
        "Recommended portfolio action",
        "What could change the decision",
    ):
        assert label in block


def test_environment_portfolio_and_history_communicate_current_state() -> None:
    source = Path("app_impl.py").read_text(encoding="utf-8")
    assert "What current market and macro evidence says" in source
    assert "Where capital is positioned, why it is there" in source
    assert "The latest decision, what happened next" in source
    assert "Portfolio implication" in source
    assert "Why the portfolio is positioned this way" in source
    assert "Outcome status" in source


def test_operational_detail_follows_surface_synopses() -> None:
    entrypoint = Path("app.py").read_text(encoding="utf-8")
    for marker in (
        "LIVE_TODAY_OPERATING_CONTEXT",
        "LIVE_ENVIRONMENT_MARKET_TABLE",
        "PAPER_DECISION_CONTROLS",
        "LIVE_PORTFOLIO_MARKS",
        "OPERATING_REPORT_HISTORY",
        "CIO_REPORT_ARCHIVE",
    ):
        assert marker in entrypoint
    assert "Administrator operations" in entrypoint
    assert "Production smoke test" in entrypoint
    assert "paper decision approval insertion point is unavailable" in entrypoint
    navigation = entrypoint[
        entrypoint.index("def _render_navigation_with_admin_control") :
    ]
    navigation = navigation[: navigation.index("def _compatible_metric_grid")]
    assert "Production smoke test" not in navigation


def test_mobile_hero_is_compact_and_direct() -> None:
    source = Path("premium_ui.py").read_text(encoding="utf-8")
    assert "Today's capital briefing" in source
    assert "Today's market environment" in source
    assert "Current portfolio position" in source
    assert "Decisions, actions and learning" in source
    assert ".hero-title{font-size:1.55rem" in source
    assert ".hero-meta .signal-chip:nth-child(2)" in source


def test_paper_implementation_uses_plain_language() -> None:
    source = Path("cio_pending_transactions_ui.py").read_text(encoding="utf-8")
    assert 'st.subheader("Paper implementation status")' in source
    assert "How the latest CIO conclusion translates" in source
    assert "CIO Pending Transaction Recommendations" not in source
