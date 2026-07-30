from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected one match in {path}, found {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_before(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(
            f"expected one insertion marker in {path}, found {count}: {marker!r}"
        )
    target.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")


def replace_between(
    path: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    start_count = text.count(start_marker)
    end_count = text.count(end_marker)
    if start_count != 1 or end_count != 1:
        raise RuntimeError(
            f"invalid block markers in {path}: start={start_count}, end={end_count}"
        )
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    target.write_text(
        text[:start] + replacement.rstrip() + "\n\n" + text[end:],
        encoding="utf-8",
    )


# Make every visual hero explain the purpose of the operating surface directly.
replace_once(
    "premium_ui.py",
    '        title="What deserves attention",\n        copy=(\n            "A quiet, portfolio-level view of the few developments that may "\n            "matter now. Everything else remains in the background."\n        ),\n',
    '        title="Today\'s capital briefing",\n        copy=(\n            "What changed, why it matters to the portfolio, and what the CIO "\n            "recommends now."\n        ),\n',
)
replace_once(
    "premium_ui.py",
    '        title="Conditions shaping capital",\n        copy=(\n            "Growth, inflation, liquidity, policy and cross-asset evidence are "\n            "resolved into a simple field of portfolio relevance."\n        ),\n',
    '        title="Today\'s market environment",\n        copy=(\n            "Current growth, inflation, policy, liquidity and cross-asset evidence, "\n            "with the portfolio implication stated plainly."\n        ),\n',
)
replace_once(
    "premium_ui.py",
    '        title="How the portfolio is positioned",\n        copy=(\n            "Sizing, funding, concentration and implementation are translated "\n            "into one understandable map of deployed and available capital."\n        ),\n',
    '        title="Current portfolio position",\n        copy=(\n            "Where capital sits, why it is positioned there, and what portfolio "\n            "action is pending or deliberately absent."\n        ),\n',
)
replace_once(
    "premium_ui.py",
    '        title="What the system decided and learned",\n        copy=(\n            "Every conclusion, thesis, paper action and observed outcome remains "\n            "connected in a calm, inspectable decision trail."\n        ),\n',
    '        title="Decisions, actions and learning",\n        copy=(\n            "The latest CIO conclusion, what happened next, and what the governed "\n            "record has learned over time."\n        ),\n',
)
replace_once(
    "premium_ui.py",
    '''            .hero-card{padding:1.2rem 1rem;min-height:auto}
            .hero-title{font-size:2rem}
''',
    '''            .hero-shell{margin-bottom:.55rem}
            .hero-card{padding:.9rem 1rem;min-height:auto}
            .hero-title{font-size:1.55rem;line-height:1.08}
            .hero-copy{font-size:.82rem;line-height:1.45;margin:.55rem 0 0}
            .hero-kicker{font-size:.56rem;margin-bottom:.5rem}
            .hero-meta{margin-top:.65rem;gap:.3rem}
            .signal-chip{font-size:.62rem;padding:.3rem .5rem}
            .hero-meta .signal-chip:nth-child(2),
            .hero-meta .signal-chip:nth-child(3),
            .hero-meta .signal-chip:nth-child(4){display:none}
''',
)

# Shared plain-language helpers used by all four operating surfaces.
insert_before(
    "app_impl.py",
    "def _render_today() -> None:\n",
    '''def _plain_text(value: object, fallback: str) -> str:
    text = "" if value is None else str(value).strip()
    return text or fallback


def _joined_items(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, (list, tuple)):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return " • ".join(cleaned) if cleaned else fallback
    return fallback


def _status_title(value: object, fallback: str = "Unavailable") -> str:
    text = "" if value is None else str(value).strip()
    return text.replace("_", " ").title() if text else fallback


def _market_session(snapshot: dict[str, object]) -> str:
    state = snapshot.get("market_open")
    return "Open" if state is True else "Closed" if state is False else "Unavailable"


def _coverage_label(snapshot: dict[str, object]) -> str:
    return (
        f"{int(snapshot.get('quote_count', 0) or 0)}/"
        f"{int(snapshot.get('expected_quote_count', 0) or 0)}"
    )


def _deployment_label(*, cash: float, nav: float) -> str:
    if nav <= 0:
        return "Unavailable"
    invested = max(float(nav) - float(cash), 0.0)
    return f"{invested / float(nav):.0%} deployed"


''',
)

replace_between(
    "app_impl.py",
    "def _render_today() -> None:\n",
    "def _render_environment() -> None:\n",
    '''def _render_today() -> None:
    briefing = _latest("daily_cio_briefing")
    theses = _latest_theses()
    live_market = load_live_market_console()
    totals = get_portfolio_totals()
    _today_construction = _latest("portfolio_construction")

    page_header(
        "Today's CIO briefing",
        (
            "The current portfolio conclusion, the evidence that matters, what changed, "
            "and the action the CIO recommends now."
        ),
        "01",
    )

    if briefing is None:
        signal_panel(
            "Daily CIO briefing // unavailable",
            "No governed CIO conclusion is available yet",
            (
                "The portfolio remains unchanged until opportunity comparison, independent "
                "review, CIO synthesis, and construction complete successfully."
            ),
            variant="today",
        )
        metric_grid(
            (
                ("U.S. session", _market_session(live_market), "Live provider clock"),
                ("Live coverage", _coverage_label(live_market), "Governed instruments"),
                ("Portfolio posture", _deployment_label(cash=totals["cash"], nav=totals["nav"]), "Current capital"),
                ("Decision state", "Standby", "Fail-closed"),
            ),
            variant="today",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card(
                "What deserves attention",
                _plain_text(
                    live_market.get("detail"),
                    "The CIO has not published a completed portfolio conclusion yet.",
                ),
            )
        with right:
            text_card(
                "What could change the state",
                (
                    "A completed evidence comparison, independent review, CIO synthesis, "
                    "and feasible construction are required before capital can change."
                ),
            )
    else:
        status = _status_title(briefing.get("status"))
        confidence = briefing.get("confidence")
        construction = briefing.get("construction_status")
        decision = _plain_text(
            briefing.get("portfolio_decision"),
            "Maintain the current portfolio posture.",
        )
        why_it_matters = _plain_text(
            briefing.get("why_it_matters"),
            "No additional portfolio-level implication was recorded.",
        )
        developments = briefing.get("material_developments", [])
        attention = _joined_items(
            developments,
            _plain_text(
                briefing.get("opportunity_or_risk"),
                "No separate material development requires portfolio action.",
            ),
        )
        signal_panel(
            f"Daily CIO briefing // {status}",
            decision,
            why_it_matters,
            variant="today",
        )
        st.caption(
            f"Briefing as of {format_datetime(briefing.get('as_of'))} · "
            f"Decision reference {_briefing_identifier(briefing)}"
        )
        metric_grid(
            (
                ("U.S. session", _market_session(live_market), "Live provider clock"),
                ("Live coverage", _coverage_label(live_market), "Governed instruments"),
                ("Portfolio posture", _deployment_label(cash=totals["cash"], nav=totals["nav"]), "Current capital"),
                (
                    "CIO state",
                    status,
                    "Not scored" if confidence is None else f"{float(confidence):.0%} confidence",
                ),
            ),
            variant="today",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card("What deserves attention", attention)
            st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
            text_card(
                "What changed",
                _plain_text(
                    briefing.get("what_changed"),
                    "No material change was recorded since the previous governed briefing.",
                ),
            )
        with right:
            text_card("Why it matters to the portfolio", why_it_matters)
            st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
            callout_card(
                "Recommended portfolio action",
                decision,
                (
                    "Paper implementation remains separate and cannot alter the CIO conclusion."
                ),
            )
        text_card(
            "What could change the decision",
            _joined_items(
                briefing.get("evidence_that_changes_conclusion", []),
                "No additional decision-change conditions were recorded.",
            ),
        )
        with st.expander("Decision evidence and audit reference"):
            st.write(
                "Opportunity or risk: "
                + _plain_text(
                    briefing.get("opportunity_or_risk"),
                    "No separate opportunity or risk vector was recorded.",
                )
            )
            st.write(f"Decision: {_briefing_identifier(briefing)}")
            st.write(
                "Candidate: "
                f"{briefing.get('candidate_identifier') or 'No qualified candidate'}"
            )
            st.write(f"Cycle: {briefing.get('cycle_identifier') or 'Unavailable'}")
            journal = briefing.get("journal", {})
            st.write(f"Journal sequence: {journal.get('sequence') if isinstance(journal, dict) else 'Unavailable'}")

    with st.expander("How the Today surface works"):
        surface_story(
            "Today",
            (
                ("Observe", "Continuous market intelligence remains in the background."),
                ("Resolve", "Only material portfolio implications advance to the CIO."),
                ("Act", "Capital changes only after construction and implementation validate."),
            ),
        )

    page_header(
        "Current capital position",
        "The sole governed portfolio at today's decision point.",
        "02",
    )
    metric_grid(
        (
            ("Portfolio value", format_currency(totals["nav"]), "Canonical NAV"),
            ("Available cash", format_currency(totals["cash"]), "Optionality reserve"),
            ("Total P&L", format_currency(totals.get("total_pnl", 0.0)), format_percent(totals["total_return"])),
            ("Today P&L", format_currency(totals.get("day_pnl", 0.0)), format_percent(totals.get("day_return", 0.0))),
        ),
        variant="today",
    )
    allocation_bar(cash=totals["cash"], nav=totals["nav"])

    # LIVE_TODAY_OPERATING_CONTEXT


''',
)

replace_between(
    "app_impl.py",
    "def _render_environment() -> None:\n",
    "def _render_portfolio() -> None:\n",
    '''def _render_environment() -> None:
    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
    live_market = load_live_market_console()
    latest_briefing = _latest("daily_cio_briefing")

    page_header(
        "Environment synopsis",
        (
            "What current market and macro evidence says, what deserves attention, "
            "and how the evidence affects the portfolio conclusion."
        ),
        "01",
    )

    quote_coverage = _coverage_label(live_market)
    unemployment = "Unavailable" if readings is None else f"{readings.unemployment_rate:.1f}%"
    inflation = "Unavailable" if readings is None else f"{readings.inflation_rate:.2f}%"
    policy_rate = "Unavailable" if readings is None else f"{readings.federal_funds_rate:.2f}%"

    if isinstance(environment, dict):
        headline = _plain_text(environment.get("headline"), "Current environment")
        summary = _plain_text(
            environment.get("summary"),
            "No additional governed environment summary is available.",
        )
        signal_panel(
            "Environment // governed",
            headline,
            summary,
            variant="environment",
        )
        metric_grid(
            (
                ("Regime", environment.get("regime", "Unavailable"), "Governed classification"),
                ("Live coverage", quote_coverage, "Cross-asset wrappers"),
                ("Estimated inflation", inflation, "Price pressure"),
                ("Federal funds", policy_rate, "Policy rate"),
            ),
            variant="environment",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card(
                "What deserves attention",
                _joined_items(
                    environment.get("review_conditions", []),
                    summary,
                ),
            )
        with right:
            text_card(
                "Portfolio implication",
                _plain_text(
                    environment.get("portfolio_impact"),
                    _plain_text(
                        latest_briefing.get("why_it_matters") if isinstance(latest_briefing, dict) else None,
                        "The environment record does not independently authorize a portfolio change.",
                    ),
                ),
            )
    elif live_market.get("status") in {"connected", "partial"} and readings is not None:
        macro_summary = (
            f"Live quote coverage is {quote_coverage}. Unemployment is {unemployment}, "
            f"estimated inflation is {inflation}, and the federal funds rate is {policy_rate}. "
            "No separate regime label has been synthesized from those readings."
        )
        signal_panel(
            "Environment // provider backed",
            "Live market and macro evidence is available",
            macro_summary,
            variant="environment",
        )
        metric_grid(
            (
                ("Live coverage", quote_coverage, "Cross-asset wrappers"),
                ("Unemployment", unemployment, "Labor market"),
                ("Estimated inflation", inflation, "Price pressure"),
                ("Federal funds", policy_rate, "Policy rate"),
            ),
            variant="environment",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card(
                "What deserves attention",
                _plain_text(
                    latest_briefing.get("what_changed") if isinstance(latest_briefing, dict) else None,
                    "No separate environment warning was recorded in the latest CIO briefing.",
                ),
            )
        with right:
            text_card(
                "Portfolio implication",
                _plain_text(
                    latest_briefing.get("why_it_matters") if isinstance(latest_briefing, dict) else None,
                    "Current evidence is included in the CIO process but is not independently actionable.",
                ),
            )
        text_card(
            "What could change the assessment",
            _joined_items(
                latest_briefing.get("evidence_that_changes_conclusion", [])
                if isinstance(latest_briefing, dict)
                else [],
                "A material change in growth, inflation, policy, liquidity, or cross-asset evidence would trigger review.",
            ),
        )
    else:
        detail = _plain_text(
            live_market.get("detail"),
            str(dashboard_data.status),
        )
        signal_panel(
            "Environment // incomplete",
            "Operating environment evidence is incomplete",
            detail,
            variant="environment",
        )
        metric_grid(
            (
                ("Live coverage", quote_coverage, "Cross-asset wrappers"),
                ("Unemployment", unemployment, "Labor market"),
                ("Estimated inflation", inflation, "Price pressure"),
                ("Federal funds", policy_rate, "Policy rate"),
            ),
            variant="environment",
        )
        text_card(
            "What deserves attention",
            "Provider or macro evidence must recover before the environment can be treated as complete.",
        )

    with st.expander("How the Environment surface works"):
        surface_story(
            "Environment",
            (
                ("Growth", "Economic momentum and labor conditions."),
                ("Inflation", "Price pressure and policy sensitivity."),
                ("Liquidity", "Rates, funding and cross-asset transmission."),
            ),
        )

    # LIVE_ENVIRONMENT_MARKET_TABLE

    page_header(
        "Economic detail",
        "Provider-backed macro readings used as evidence in opportunity comparison.",
        "02",
    )
    if readings is None:
        st.warning("Live economic readings are unavailable.")
        st.caption(str(dashboard_data.status))
        return
    metric_grid(
        (
            ("Unemployment", unemployment, "Labor market"),
            ("Estimated inflation", inflation, "Price pressure"),
            ("Federal funds", policy_rate, "Policy rate"),
            ("Use", "Evidence only", "Compared across candidates"),
        ),
        variant="environment",
    )


''',
)

replace_between(
    "app_impl.py",
    "def _render_portfolio() -> None:\n",
    "def _render_history() -> None:\n",
    '''def _render_portfolio() -> None:
    construction = _latest("portfolio_construction")
    briefing = _latest("daily_cio_briefing")
    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    if mandate is None:
        st.warning("The canonical paper portfolio is unavailable.")
        return

    nav = float(mandate["nav"])
    cash = float(mandate["cash"])
    invested = max(nav - cash, 0.0)
    deployed = 0.0 if nav <= 0 else invested / nav
    holdings = mandate.get("holdings", [])
    posture = "Fully in cash" if invested <= 0.01 else f"{deployed:.0%} invested"
    decision = _plain_text(
        briefing.get("portfolio_decision") if isinstance(briefing, dict) else None,
        "No new portfolio action is currently authorized.",
    )
    positioning_reason = _plain_text(
        briefing.get("why_it_matters") if isinstance(briefing, dict) else None,
        (
            "Capital remains in its current position until a governed opportunity "
            "clears evidence, risk, cost, liquidity, and construction controls."
        ),
    )

    page_header(
        "Portfolio synopsis",
        "Where capital is positioned, why it is there, and what action is pending now.",
        "01",
    )
    signal_panel(
        "Portfolio // current posture",
        posture,
        positioning_reason,
        variant="portfolio",
    )
    metric_grid(
        (
            ("Portfolio value", format_currency(nav), "Canonical NAV"),
            ("Available cash", format_currency(cash), "Optionality reserve"),
            ("Capital deployed", f"{deployed:.0%}", "Current exposure"),
            ("Total P&L", format_currency(mandate.get("total_pnl", 0.0)), format_percent(mandate["total_return"])),
        ),
        variant="portfolio",
    )
    left, right = st.columns(2, gap="large")
    with left:
        text_card("Why the portfolio is positioned this way", positioning_reason)
        st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
        text_card(
            "Current holdings",
            (
                "The portfolio holds cash only."
                if not holdings
                else f"{len(holdings)} governed position{'s' if len(holdings) != 1 else ''} are currently recorded."
            ),
        )
    with right:
        callout_card("Recommended portfolio action", decision)
        st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
        if construction is None:
            text_card(
                "Implementation status",
                "No construction change is queued. Existing capital remains in its current state.",
            )
        else:
            trade_count = len(construction.get("trades", []))
            text_card(
                "Implementation status",
                (
                    f"{_status_title(construction.get('status'))}. "
                    f"{trade_count} proposed paper transaction{'s' if trade_count != 1 else ''}."
                ),
            )

    with st.expander("How the Portfolio surface works"):
        surface_story(
            "Portfolio",
            (
                ("Size", "Translate conviction into a feasible portfolio weight."),
                ("Fund", "Identify the best source of capital and opportunity cost."),
                ("Validate", "Confirm concentration, cost and paper implementation."),
            ),
        )

    # PAPER_DECISION_CONTROLS

    page_header(
        "Construction detail",
        "Sizing, funding, costs, and implementation controls behind the current posture.",
        "02",
    )
    if construction is None:
        signal_panel(
            "Construction map // idle",
            "No implementation change queued",
            "No canonical construction result is required for the current no-change posture.",
            variant="portfolio",
        )
    else:
        status = _status_title(construction.get("status"))
        signal_panel(
            f"Construction map // {status}",
            "Implementation geometry resolved",
            (
                "Sizing and funding are visible for review, but construction cannot "
                "alter the CIO decision or submit broker orders."
            ),
            variant="portfolio",
        )
        metric_grid(
            (
                ("Construction state", status, "Paper implementation"),
                ("Turnover", format_percent(construction.get("turnover", 0.0)), "Portfolio movement"),
                ("Estimated cost", format_percent(construction.get("estimated_cost_return", 0.0)), "Return drag"),
                ("Expected improvement", format_percent(construction.get("expected_return_improvement", 0.0)), "Net opportunity"),
            ),
            variant="portfolio",
        )
        if construction.get("trades"):
            with st.expander("Proposed paper implementation"):
                display_frame(pd.DataFrame(construction["trades"]))
        for block in construction.get("blocks", []):
            st.warning(block)

    page_header(
        "Holdings and capital path",
        PORTFOLIO_OBJECTIVE,
        "03",
    )
    metric_grid(
        (
            ("NAV", format_currency(mandate["nav"]), "Canonical value"),
            ("Total P&L", format_currency(mandate.get("total_pnl", 0.0)), format_percent(mandate["total_return"])),
            ("Realized", format_currency(mandate.get("realized_pnl", 0.0)), "Closed positions and lifecycle cash"),
            ("Unrealized", format_currency(mandate.get("unrealized_pnl", 0.0)), "Current marks"),
        ),
        variant="portfolio",
    )
    st.caption(
        "Valuation as of "
        f"{format_datetime(mandate.get('as_of'))} · "
        f"Cash {format_currency(mandate['cash'])} · "
        f"Accounting residual {format_currency(mandate.get('accounting_residual', 0.0))}"
    )
    allocation_bar(cash=mandate["cash"], nav=mandate["nav"])

    # LIVE_PORTFOLIO_MARKS

    holdings_tab, trades_tab, history_tab = st.tabs(
        ["Positions", "Implementation", "Capital path"]
    )
    with holdings_tab:
        holdings = mandate["holdings"]
        if not holdings:
            st.info("No current holdings are recorded.")
        else:
            frame = pd.DataFrame(holdings)
            columns = [
                column
                for column in (
                    "symbol", "asset_class", "quantity", "current_price", "cost_basis",
                    "market_value", "unrealized_gain", "unrealized_return",
                    "price_currency", "updated_at",
                )
                if column in frame.columns
            ]
            frame = frame[columns] if columns else frame
            if "updated_at" in frame.columns:
                frame["updated_at"] = frame["updated_at"].map(format_datetime)
            display_frame(frame)
    with trades_tab:
        trades = mandate["trades"]
        if not trades:
            st.info("No paper trades have been recorded.")
        else:
            frame = pd.DataFrame(trades)
            columns = [
                column
                for column in (
                    "created_at", "side", "symbol", "asset_class", "quantity", "price",
                    "gross_amount_base", "cost_basis_relieved_base", "realized_pnl_base",
                    "cost_amount_base", "rationale",
                )
                if column in frame.columns
            ]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)
    with history_tab:
        snapshots = mandate["snapshots"]
        if not snapshots:
            st.info("No portfolio snapshots are available.")
        else:
            frame = pd.DataFrame(snapshots)
            if "created_at" in frame.columns and "nav" in frame.columns:
                chart = frame.copy()
                chart["created_at"] = pd.to_datetime(chart["created_at"])
                st.line_chart(chart.sort_values("created_at").set_index("created_at")["nav"])
            columns = [
                column
                for column in (
                    "created_at", "cash_base_total", "holdings_value", "nav", "total_pnl",
                    "realized_pnl", "unrealized_pnl", "total_return",
                )
                if column in frame.columns
            ]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)


''',
)

replace_between(
    "app_impl.py",
    "def _render_history() -> None:\n",
    'st.session_state.setdefault("dark_mode", True)\n',
    '''def _render_history() -> None:
    briefings = _history("daily_cio_briefing")
    evaluations = _history("decision_evaluation")
    theses = _latest_theses()
    trades = get_trade_history(limit=250)

    latest_briefing = briefings[0] if briefings else {}
    latest_evaluation = evaluations[0] if evaluations else {}
    latest_thesis = theses[0] if theses else {}
    latest_trade = trades[0] if trades else {}
    latest_decision = _plain_text(
        latest_briefing.get("portfolio_decision"),
        "Awaiting the first governed CIO briefing.",
    )

    page_header(
        "History synopsis",
        "The latest decision, what happened next, and the state of the governed record.",
        "01",
    )
    signal_panel(
        f"Latest CIO record // {_status_title(latest_briefing.get('status'), 'Awaiting briefing')}",
        latest_decision,
        _plain_text(
            latest_briefing.get("why_it_matters"),
            "No additional portfolio implication is recorded for the latest decision.",
        ),
        variant="history",
    )
    metric_grid(
        (
            ("Latest briefing", format_datetime(latest_briefing.get("as_of")), "Most recent CIO record"),
            ("CIO briefings", len(briefings), "Recorded decisions"),
            ("Evaluations", len(evaluations), "Matured outcome reviews"),
            ("Paper trades", len(trades), "Execution journal"),
        ),
        variant="history",
    )
    left, right = st.columns(2, gap="large")
    with left:
        text_card("Most recent decision", latest_decision)
        st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
        text_card(
            "What changed at that decision",
            _plain_text(
                latest_briefing.get("what_changed"),
                "No material change was recorded for the latest briefing.",
            ),
        )
    with right:
        text_card(
            "Outcome status",
            _plain_text(
                latest_evaluation.get("outcome"),
                "The decision horizon has not produced a matured evaluation yet.",
            ),
        )
        st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
        text_card(
            "Execution status",
            (
                f"{latest_trade.get('side', '')} {latest_trade.get('symbol', '')}".strip()
                if latest_trade
                else "No paper trade was recorded for the current no-action posture."
            ),
        )
    callout_card(
        "Learning state",
        (
            _plain_text(latest_evaluation.get("process_verdict"), "No matured process verdict yet.")
            if evaluations
            else "Learning remains observation-only until decision horizons mature."
        ),
        (
            f"{len(theses)} living thesis record{'s' if len(theses) != 1 else ''} currently monitored."
        ),
    )

    with st.expander("How the History surface works"):
        surface_story(
            "History",
            (
                ("Record", "Preserve the original evidence and governed conclusion."),
                ("Observe", "Wait for the complete decision horizon and real outcomes."),
                ("Evaluate", "Separate process quality from outcome quality."),
                ("Learn", "Submit evidence for governance review without self-modifying."),
            ),
        )

    # OPERATING_REPORT_HISTORY
    # CIO_REPORT_ARCHIVE

    page_header(
        "Detailed decision trail",
        (
            "Every CIO briefing, outcome, thesis, and paper action remains visible "
            "as governed institutional memory."
        ),
        "02",
    )
    activity_rail(
        (
            ("Decision", latest_decision, format_datetime(latest_briefing.get("as_of"))),
            (
                "Outcome",
                latest_evaluation.get("outcome") or "Awaiting matured evaluation",
                latest_evaluation.get("process_verdict") or "No process verdict",
            ),
            (
                "Thesis",
                latest_thesis.get("asset") or "No thesis recorded",
                latest_thesis.get("state") or "No lifecycle state",
            ),
            (
                "Execution",
                (f"{latest_trade.get('side', '')} {latest_trade.get('symbol', '')}".strip() or "No paper trade recorded"),
                format_datetime(latest_trade.get("created_at")),
            ),
        )
    )

    brief_tab, eval_tab, thesis_tab, trade_tab = st.tabs(
        ["Decisions", "Outcomes", "Theses", "Execution"]
    )
    with brief_tab:
        if not briefings:
            st.info("No canonical CIO briefings have been recorded.")
        else:
            display_frame(
                pd.DataFrame(
                    {
                        "As of": format_datetime(item.get("as_of")),
                        "Status": item.get("status"),
                        "Decision": item.get("portfolio_decision"),
                        "Confidence": item.get("confidence"),
                        "Decision ID": _briefing_identifier(item),
                    }
                    for item in briefings
                )
            )
    with eval_tab:
        if not evaluations:
            st.info("Evaluations appear after the decision horizon has observable outcomes.")
        else:
            display_frame(
                pd.DataFrame(
                    {
                        "Decision": item.get("decision_identifier"),
                        "Process": item.get("process_verdict"),
                        "Outcome": item.get("outcome"),
                        "Value added": item.get("value_added_vs_best_alternative"),
                        "Brier score": item.get("brier_score"),
                    }
                    for item in evaluations
                )
            )
    with thesis_tab:
        if not theses:
            st.info("No active or historical ownership theses are recorded.")
        else:
            display_frame(
                pd.DataFrame(
                    {
                        "Thesis": item.get("identifier"),
                        "Asset": item.get("asset"),
                        "State": item.get("state"),
                        "Confidence": item.get("current_confidence"),
                        "Next review": format_datetime(item.get("next_review_at")),
                    }
                    for item in theses
                )
            )
    with trade_tab:
        if not trades:
            st.info("No paper trades have been recorded.")
        else:
            frame = pd.DataFrame(trades)
            columns = [
                column
                for column in (
                    "created_at", "side", "symbol", "asset_class", "quantity", "price",
                    "gross_amount_base", "cost_basis_relieved_base", "realized_pnl_base",
                    "cost_amount_base", "rationale",
                )
                if column in frame.columns
            ]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)


''',
)

# Move the administrator-only production test out of the user-facing page hierarchy.
replace_between(
    "app.py",
    "def _render_navigation_with_admin_control(options):\n",
    "def _compatible_metric_grid(metrics, *, variant: str = \"today\") -> None:\n",
    '''def _render_navigation_with_admin_control(options):
    """Keep the four primary tabs free of administrator operations."""

    return _original_render_navigation(options)


''',
)
replace_between(
    "app.py",
    "def _safe_render_sidebar() -> None:\n",
    "def _safe_render_app_header(active_page: str) -> None:\n",
    '''def _safe_render_sidebar() -> None:
    """Render the brand and administrator operations in the sidebar."""

    with _premium_ui.st.sidebar:
        _premium_ui.st.markdown(
            '<div class="sidebar-brand">'
            '<div class="sidebar-mark">CI</div>'
            '<div class="sidebar-brand-title">Capital Intelligence</div>'
            '<div class="sidebar-brand-copy">A continuously operating decision system for one governed portfolio.</div>'
            '<div class="sidebar-system">System online</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        _premium_ui.st.caption("Four distinct surfaces. One governed portfolio.")
        principal = globals().get("authenticated_principal")
        is_render_host = bool(os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip())
        if (
            is_render_host
            and principal is not None
            and getattr(principal, "is_administrator", False)
        ):
            _premium_ui.st.divider()
            _premium_ui.st.caption("Administrator operations")
            if _premium_ui.st.button(
                "Production smoke test",
                key="open-production-smoke-test-main",
                help=(
                    "Verify persistence, the CIO operator, provider evidence, governed "
                    "paper outcomes, and encrypted backups."
                ),
                use_container_width=True,
            ):
                _premium_ui.st.session_state["production_smoke_test_open"] = True


''',
)

replace_between(
    "app.py",
    "# Today is the immediate operating summary: live provider/session state and the exact\n",
    "# Keep the execution worker alive on every Streamlit surface.\n",
    '''# Provider and operational detail is injected only after each surface has presented
# its plain-language synopsis. Checked markers make deployment fail loudly if the
# information hierarchy changes without updating these integrations.
_today_operating_marker = "    # LIVE_TODAY_OPERATING_CONTEXT\\n"
if _source.count(_today_operating_marker) != 1:
    raise RuntimeError("Today operating context insertion point is unavailable")
_source = _source.replace(
    _today_operating_marker,
    '    page_header(\\n'
    + '        "Operating context",\\n'
    + '        "Live provider status and paper implementation supporting the CIO briefing.",\\n'
    + '        "03",\\n'
    + '    )\\n'
    + '    render_live_market_status()\\n'
    + '    render_pending_transaction_report(\\n'
    + '        construction=_today_construction,\\n'
    + '        briefing=briefing,\\n'
    + '    )\\n',
    1,
)

_environment_market_marker = "    # LIVE_ENVIRONMENT_MARKET_TABLE\\n"
if _source.count(_environment_market_marker) != 1:
    raise RuntimeError("Environment market table insertion point is unavailable")
_source = _source.replace(
    _environment_market_marker,
    '    page_header(\\n'
    + '        "Cross-asset market detail",\\n'
    + '        "Current provider-backed evidence across the governed wrapper universe.",\\n'
    + '        "02",\\n'
    + '    )\\n'
    + '    render_live_environment_market_table()\\n',
    1,
)

_portfolio_controls_marker = "    # PAPER_DECISION_CONTROLS\\n"
if _source.count(_portfolio_controls_marker) != 1:
    raise RuntimeError("Portfolio paper control insertion point is unavailable")
_source = _source.replace(
    _portfolio_controls_marker,
    '    render_pending_transaction_report(\\n'
    + '        construction=construction,\\n'
    + '        briefing=briefing,\\n'
    + '    )\\n'
    + '    render_paper_decision_controls(\\n'
    + '        construction=construction,\\n'
    + '        briefing=briefing,\\n'
    + '        principal=globals().get("authenticated_principal"),\\n'
    + '    )\\n',
    1,
)

_portfolio_marks_marker = "    # LIVE_PORTFOLIO_MARKS\\n"
if _source.count(_portfolio_marks_marker) != 1:
    raise RuntimeError("Portfolio live mark insertion point is unavailable")
_source = _source.replace(
    _portfolio_marks_marker,
    '    render_live_portfolio_marks(mandate)\\n',
    1,
)

_history_operating_marker = "    # OPERATING_REPORT_HISTORY\\n"
if _source.count(_history_operating_marker) != 1:
    raise RuntimeError("History operating report insertion point is unavailable")
_source = _source.replace(
    _history_operating_marker,
    '    render_operating_report_history()\\n',
    1,
)

_history_archive_marker = "    # CIO_REPORT_ARCHIVE\\n"
if _source.count(_history_archive_marker) != 1:
    raise RuntimeError("History CIO archive insertion point is unavailable")
_source = _source.replace(
    _history_archive_marker,
    '    render_cio_report_archive()\\n',
    1,
)

''',
)

replace_once(
    "cio_pending_transactions_ui.py",
    '    st.subheader("CIO Pending Transaction Recommendations")\n',
    '    st.subheader("Paper implementation status")\n',
)
replace_once(
    "cio_pending_transactions_ui.py",
    '''    st.caption(
        f"Paper trading launch: {report['paper_trading_start_label']} · "
        f"Execution state: {str(report.get('execution_state', 'unavailable')).replace('_', ' ').title()} · "
        "Exact canonical CIO construction"
    )
''',
    '''    st.caption(
        "How the latest CIO conclusion translates into governed paper implementation · "
        f"Launch: {report['paper_trading_start_label']} · "
        f"Execution: {str(report.get('execution_state', 'unavailable')).replace('_', ' ').title()}"
    )
''',
)

Path("tests/test_surface_information_hierarchy.py").write_text(
    '''from pathlib import Path


def _function_block(source: str, name: str, next_name: str | None) -> str:
    start = source.index(f"def {name}() -> None:")
    end = len(source) if next_name is None else source.index(f"def {next_name}() -> None:", start)
    return source[start:end]


def test_every_surface_leads_with_a_plain_language_synopsis() -> None:
    source = Path("app_impl.py").read_text(encoding="utf-8")
    expectations = (
        ("_render_today", "_render_environment", "Today's CIO briefing", "How the Today surface works"),
        ("_render_environment", "_render_portfolio", "Environment synopsis", "How the Environment surface works"),
        ("_render_portfolio", "_render_history", "Portfolio synopsis", "How the Portfolio surface works"),
        ("_render_history", None, "History synopsis", "How the History surface works"),
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
    navigation = entrypoint[entrypoint.index("def _render_navigation_with_admin_control") :]
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
''',
    encoding="utf-8",
)

Path(__file__).unlink()
