from __future__ import annotations


def test_entrypoints_use_explicit_imports_instead_of_source_execution() -> None:
    for filename in ("app.py", "secure_app.py", "render_app.py"):
        source = open(filename, encoding="utf-8").read()
        assert "exec(compile" not in source
        assert "_replace_source_once" not in source
        assert "read_text(encoding=\"utf-8\")" not in source
    assert "def render_application" in open("app.py", encoding="utf-8").read()
    assert "def render_application" in open("app_impl.py", encoding="utf-8").read()
    assert "def run_authenticated_app" in open("secure_app.py", encoding="utf-8").read()
    assert "from secure_app import run_authenticated_app" in open("render_app.py", encoding="utf-8").read()


def test_materialized_surface_integrations_have_no_runtime_markers() -> None:
    source = open("app_impl.py", encoding="utf-8").read()
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
        assert marker not in source
    assert '@st.fragment(run_every="30s")' in source
    assert "render_background_paper_execution_worker" in source
