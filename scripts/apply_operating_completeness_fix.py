from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement anchor, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_once(path: str, anchor: str, addition: str) -> None:
    replace_once(path, anchor, anchor + addition)


# Preserve a decision reference for governed no-action briefings. The canonical daily
# briefing already has a stable identifier even when no candidate-specific decision ID
# exists, so pending reports and their archive should retain that identifier.
insert_once(
    "cio_pending_transactions.py",
    '''def _governed_no_action_briefing(
    briefing: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(briefing, Mapping):
        return False
    identifier = str(briefing.get("identifier", "")).strip()
    as_of = str(briefing.get("as_of", "")).strip()
    status = str(briefing.get("status", "")).strip().lower()
    portfolio_decision = str(briefing.get("portfolio_decision", "")).strip()
    return bool(
        identifier
        and as_of
        and portfolio_decision
        and status in _GOVERNED_NO_ACTION_STATUSES
    )


''',
    '''def _briefing_decision_identifier(
    briefing: Mapping[str, Any] | None,
) -> str:
    if not isinstance(briefing, Mapping):
        return ""
    for field_name in ("decision_identifier", "identifier", "cycle_identifier"):
        value = str(briefing.get(field_name, "")).strip()
        if value:
            return value
    return ""


''',
)
replace_once(
    "cio_pending_transactions.py",
    '''        "decision_identifier": (
            str(briefing.get("decision_identifier", "")).strip()
            if isinstance(briefing, Mapping)
            else ""
        ),
''',
    '''        "decision_identifier": _briefing_decision_identifier(briefing),
''',
)
replace_once(
    "cio_pending_transactions.py",
    '''    decision_identifier = (
        str(briefing.get("decision_identifier", "")).strip()
        if isinstance(briefing, Mapping)
        else ""
    )
''',
    '''    decision_identifier = _briefing_decision_identifier(briefing)
''',
)

# Make the four operating surfaces truthful and complete when live provider evidence is
# available but the older diagnostic-snapshot store has not published a regime object.
insert_once(
    "app_impl.py",
    '''from providers.economic_snapshot import load_dashboard_data
''',
    '''from live_operating_console import load_live_market_console
''',
)
insert_once(
    "app_impl.py",
    '''def _diagnostic_environment() -> dict[str, Any] | None:
    try:
        return diagnostic_snapshots().latest_payload()
    except (RuntimeError, OSError):
        return None


''',
    '''def _briefing_identifier(briefing: dict[str, Any] | None) -> str:
    if not isinstance(briefing, dict):
        return "Unavailable"
    for field_name in ("decision_identifier", "identifier", "cycle_identifier"):
        value = str(briefing.get(field_name, "")).strip()
        if value:
            return value
    return "Unavailable"


''',
)
replace_once(
    "app_impl.py",
    '''                (
                    "Confidence",
                    "—" if confidence is None else f"{float(confidence):.0%}",
                    "Evidence-weighted",
                ),
''',
    '''                (
                    "Confidence",
                    "Not scored" if confidence is None else f"{float(confidence):.0%}",
                    (
                        "No-candidate conclusion"
                        if confidence is None
                        else "Evidence-weighted"
                    ),
                ),
''',
)
replace_once(
    "app_impl.py",
    '''                "Decision: "
                f"{briefing.get('decision_identifier') or 'No action decision'}"
''',
    '''                "Decision: "
                f"{_briefing_identifier(briefing)}"
''',
)
replace_once(
    "app_impl.py",
    '''    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    if isinstance(environment, dict):
        signal_panel(
            "Market field // active",
            environment.get("headline", "Current environment"),
            environment.get(
                "summary",
                "No environment summary is available.",
            ),
            variant="environment",
        )
        confidence = environment.get("confidence")
        metric_grid(
            (
                (
                    "Regime",
                    environment.get("regime", "Unavailable"),
                    "Current classification",
                ),
                (
                    "Evidence confidence",
                    "—" if confidence is None else f"{float(confidence):.0%}",
                    "Certified inputs",
                ),
                (
                    "Data status",
                    environment.get("data_status", "Unavailable"),
                    "Freshness and coverage",
                ),
                (
                    "Portfolio effect",
                    "Observed",
                    "Not independently actionable",
                ),
            ),
            variant="environment",
        )
        if environment.get("portfolio_impact"):
            callout_card(
                "Portfolio transmission",
                environment["portfolio_impact"],
            )
        if environment.get("review_conditions"):
            with st.expander("Environment review conditions"):
                st.markdown(bullet_lines(environment["review_conditions"]))
    else:
        signal_panel(
            "Market field // limited",
            "Canonical environment brief unavailable",
            (
                "Diagnostic readings remain visible, but no portfolio conclusion "
                "is inferred from incomplete environment evidence."
            ),
            variant="environment",
        )

    page_header(
        "Economic telemetry",
        "Live macro readings feeding the broader opportunity engine.",
        "02",
    )
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
''',
    '''    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
    live_market = load_live_market_console()
    if isinstance(environment, dict):
        signal_panel(
            "Market field // active",
            environment.get("headline", "Current environment"),
            environment.get(
                "summary",
                "No environment summary is available.",
            ),
            variant="environment",
        )
        confidence = environment.get("confidence")
        metric_grid(
            (
                (
                    "Regime",
                    environment.get("regime", "Unavailable"),
                    "Current classification",
                ),
                (
                    "Evidence confidence",
                    "Not scored" if confidence is None else f"{float(confidence):.0%}",
                    "Certified inputs",
                ),
                (
                    "Data status",
                    environment.get("data_status", "Unavailable"),
                    "Freshness and coverage",
                ),
                (
                    "Portfolio effect",
                    "Observed",
                    "Not independently actionable",
                ),
            ),
            variant="environment",
        )
        if environment.get("portfolio_impact"):
            callout_card(
                "Portfolio transmission",
                environment["portfolio_impact"],
            )
        if environment.get("review_conditions"):
            with st.expander("Environment review conditions"):
                st.markdown(bullet_lines(environment["review_conditions"]))
    elif (
        live_market.get("status") in {"connected", "partial"}
        and readings is not None
    ):
        quote_count = int(live_market.get("quote_count", 0) or 0)
        expected_quote_count = int(
            live_market.get("expected_quote_count", 0) or 0
        )
        coverage_state = (
            "Provider complete"
            if live_market.get("status") == "connected"
            else "Provider partial"
        )
        latest_briefing = _latest("daily_cio_briefing")
        signal_panel(
            "Market field // provider backed",
            "Live environment evidence is available",
            (
                "Alpaca/IEX cross-asset quotes and FRED macro readings are current "
                "on this operating host. This evidence feeds the CIO process without "
                "being presented as a separate regime recommendation."
            ),
            variant="environment",
        )
        metric_grid(
            (
                (
                    "Regime",
                    "Not separately classified",
                    "No synthetic label",
                ),
                (
                    "Evidence confidence",
                    coverage_state,
                    "Current provider inputs",
                ),
                (
                    "Data status",
                    f"{quote_count}/{expected_quote_count} quotes + macro",
                    "Live production coverage",
                ),
                (
                    "Portfolio effect",
                    "Included in CIO",
                    "Not independently actionable",
                ),
            ),
            variant="environment",
        )
        callout_card(
            "Portfolio transmission",
            (
                str(latest_briefing.get("portfolio_decision"))
                if isinstance(latest_briefing, dict)
                and latest_briefing.get("portfolio_decision")
                else (
                    "Current provider evidence is available to the governed CIO "
                    "process; it does not independently authorize a portfolio change."
                )
            ),
        )
    else:
        detail = str(live_market.get("detail") or dashboard_data.status)
        signal_panel(
            "Market field // limited",
            "Operating environment evidence is incomplete",
            detail,
            variant="environment",
        )

    page_header(
        "Economic telemetry",
        "Live macro readings feeding the broader opportunity engine.",
        "02",
    )
''',
)
replace_once(
    "app_impl.py",
    '''                        "Decision ID": item.get("decision_identifier"),
''',
    '''                        "Decision ID": _briefing_identifier(item),
''',
)

# Clarify why a historical replay can contain every required series but still fail
# point-in-time certification at most decision cutoffs.
insert_once(
    "historical_replay_ui.py",
    '''def render_canonical_historical_replay() -> None:
''',
    '''def historical_macro_certification_detail(summary: Mapping[str, Any]) -> str:
    present = int(summary.get("present_macro_dataset_count", 0) or 0)
    required = int(summary.get("required_macro_dataset_count", 0) or 0)
    incomplete_cutoffs = int(summary.get("macro_incomplete_cutoffs", 0) or 0)
    total_cutoffs = int(summary.get("total_cutoffs", 0) or 0)
    missing = [str(item) for item in summary.get("missing_macro_datasets", [])]
    if summary.get("certification_ready") is True:
        return "Historical macro coverage is complete and live calibration is certified."
    if required > 0 and present >= required and incomplete_cutoffs > 0:
        return (
            f"All {required} required macro series are present in the archive, but "
            f"point-in-time values were unavailable at {incomplete_cutoffs} of "
            f"{total_cutoffs} decision cutoffs. Those cutoffs and their observations "
            "remain excluded from live calibration."
        )
    if missing:
        return "Historical macro coverage is incomplete. Missing: " + ", ".join(missing) + "."
    return (
        "Historical macro coverage does not yet satisfy the point-in-time "
        "certification rules required for live calibration."
    )


''',
)
replace_once(
    "historical_replay_ui.py",
    '''    if not summary["certification_ready"]:
        missing = ", ".join(summary["missing_macro_datasets"])
        st.warning(
            "This replay remains available for audit, but it is not permitted to calibrate "
            "live committee confidence or CIO sizing because point-in-time macro coverage "
            "is incomplete."
            + (f" Missing: {missing}." if missing else "")
        )
''',
    '''    if not summary["certification_ready"]:
        st.warning(historical_macro_certification_detail(summary))
''',
)
replace_once(
    "historical_replay_ui.py",
    '''    "canonical_replay_summary",
''',
    '''    "canonical_replay_summary",
    "historical_macro_certification_detail",
''',
)

# Prevent long operational states and decision labels from being visually truncated on
# phones. Native Streamlit metric values and custom metric cards should wrap naturally.
replace_once(
    "premium_ui.py",
    '''        .metric-value{font-size:1.5rem;line-height:1.15;font-weight:760;letter-spacing:-.04em;color:var(--ink);margin:.7rem 0 .25rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
''',
    '''        .metric-value{font-size:1.5rem;line-height:1.15;font-weight:760;letter-spacing:-.04em;color:var(--ink);margin:.7rem 0 .25rem;white-space:normal;overflow-wrap:anywhere;word-break:break-word}
''',
)
insert_once(
    "premium_ui.py",
    '''        [data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 16px 38px var(--shadow);background:var(--panel-solid)}
''',
    '''        [data-testid="stMetricValue"]{white-space:normal!important;overflow-wrap:anywhere;word-break:break-word;line-height:1.08}
''',
)
replace_once(
    "premium_ui.py",
    '''            .metric-value{font-size:1.25rem}
''',
    '''            .metric-value{font-size:1.1rem}
            .activity-title{white-space:normal;overflow:visible;text-overflow:clip}
            [data-testid="stMetricValue"]{font-size:1.45rem!important}
''',
)

# Make no-action reports explicit on the current and archived operating surfaces.
replace_once(
    "cio_pending_transactions_ui.py",
    '''    metrics = st.columns(4)
    metrics[0].metric("Transactions", int(report["transaction_count"]))
    metrics[1].metric("Target cash", _percentage(report.get("target_cash_weight")))
    metrics[2].metric("Turnover", _percentage(report.get("turnover")))
    metrics[3].metric(
        "Expected improvement",
        _percentage(report.get("expected_return_improvement")),
    )
''',
    '''    no_transaction = report.get("report_state") == "no_transaction_recommended"
    metrics = st.columns(4)
    metrics[0].metric("Transactions", int(report["transaction_count"]))
    metrics[1].metric(
        "Target allocation",
        (
            "Unchanged"
            if no_transaction and report.get("target_cash_weight") is None
            else _percentage(report.get("target_cash_weight"))
        ),
    )
    metrics[2].metric(
        "Turnover",
        (
            "0.00%"
            if no_transaction and report.get("turnover") is None
            else _percentage(report.get("turnover"))
        ),
    )
    metrics[3].metric(
        "Expected improvement",
        (
            "Not applicable"
            if no_transaction and report.get("expected_return_improvement") is None
            else _percentage(report.get("expected_return_improvement"))
        ),
    )
''',
)
replace_once(
    "cio_report_history_ui.py",
    '''    report = reports[int(selected)]

    st.caption(
''',
    '''    report = reports[int(selected)]
    no_transaction = report.get("report_state") == "no_transaction_recommended"
    decision_reference = str(report.get("decision_identifier") or "").strip()
    if not decision_reference:
        fingerprint = str(report.get("report_fingerprint") or "").strip()
        decision_reference = f"report:{fingerprint[:16]}" if fingerprint else "Unavailable"

    st.caption(
''',
)
replace_once(
    "cio_report_history_ui.py",
    '''        "Target cash",
        _percent(report.get("target_cash_weight")),
''',
    '''        "Target allocation",
        (
            "Unchanged"
            if no_transaction and report.get("target_cash_weight") is None
            else _percent(report.get("target_cash_weight"))
        ),
''',
)
replace_once(
    "cio_report_history_ui.py",
    '''    metrics[0].metric("Turnover", _percent(report.get("turnover")))
    metrics[1].metric(
        "Expected improvement",
        _percent(report.get("expected_return_improvement")),
    )
''',
    '''    metrics[0].metric(
        "Turnover",
        (
            "0.00%"
            if no_transaction and report.get("turnover") is None
            else _percent(report.get("turnover"))
        ),
    )
    metrics[1].metric(
        "Expected improvement",
        (
            "Not applicable"
            if no_transaction and report.get("expected_return_improvement") is None
            else _percent(report.get("expected_return_improvement"))
        ),
    )
''',
)
replace_once(
    "cio_report_history_ui.py",
    '''        f"Decision: {report.get('decision_identifier') or 'Unavailable'}"
''',
    '''        f"Decision reference: {decision_reference}"
''',
)
replace_once(
    "cio_report_history_ui.py",
    '''        "Construction: "
        f"{report.get('construction_identifier') or 'Unavailable'}"
''',
    '''        "Construction: "
        f"{report.get('construction_identifier') or ('Not required' if no_transaction else 'Unavailable')}"
''',
)

Path("tests/test_operating_completeness_fixes.py").write_text(
    '''from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cio_pending_transactions import build_pending_transaction_report
from historical_replay_ui import historical_macro_certification_detail


def _briefing(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "briefing:canonical-cio:2026-07-30",
        "cycle_identifier": "canonical-cio:America/Los_Angeles:2026-07-30",
        "as_of": "2026-07-30T12:01:00+00:00",
        "status": "no_superior_opportunity",
        "portfolio_decision": "No portfolio action is required.",
    }
    payload.update(overrides)
    return payload


def test_no_action_report_retains_canonical_briefing_identifier() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc),
        execution_state="idle",
    )

    assert report["decision_identifier"] == "briefing:canonical-cio:2026-07-30"
    assert report["report_state"] == "no_transaction_recommended"
    assert report["summary"] == "No portfolio action is required."


def test_explicit_decision_identifier_remains_authoritative() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing=_briefing(decision_identifier="decision:explicit"),
        generated_at=datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc),
        execution_state="idle",
    )

    assert report["decision_identifier"] == "decision:explicit"


def test_historical_macro_message_distinguishes_series_presence_from_cutoff_coverage() -> None:
    detail = historical_macro_certification_detail(
        {
            "certification_ready": False,
            "present_macro_dataset_count": 3,
            "required_macro_dataset_count": 3,
            "macro_incomplete_cutoffs": 117,
            "total_cutoffs": 120,
            "missing_macro_datasets": [],
        }
    )

    assert "All 3 required macro series are present" in detail
    assert "117 of 120 decision cutoffs" in detail
    assert "excluded from live calibration" in detail


def test_operating_surface_source_uses_live_environment_fallback_and_wrapping() -> None:
    app_source = Path("app_impl.py").read_text(encoding="utf-8")
    style_source = Path("premium_ui.py").read_text(encoding="utf-8")

    assert "Live environment evidence is available" in app_source
    assert "Not separately classified" in app_source
    assert '"Decision ID": _briefing_identifier(item)' in app_source
    assert "white-space:normal;overflow-wrap:anywhere" in style_source
    assert '[data-testid="stMetricValue"]' in style_source
''',
    encoding="utf-8",
)

# Remove the temporary mutation machinery from the resulting product branch.
Path("scripts/apply_operating_completeness_fix.py").unlink()
workflow = Path(".github/workflows/apply-operating-completeness-fix.yml")
if workflow.exists():
    workflow.unlink()
