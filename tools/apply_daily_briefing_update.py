from __future__ import annotations

from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


app_path = Path("app.py")
app_source = app_path.read_text(encoding="utf-8")
old_insertion = '''# Add concise educational context before each surface explains its process.
_educational_briefing_insertions = (
    (
        '    with st.expander("How the Today surface works"):\\n',
        '    render_today_market_brief()\\n\\n'
        '    with st.expander("How the Today surface works"):\\n',
    ),
    (
        '    with st.expander("How the Environment surface works"):\\n',
        '    render_environment_economic_brief()\\n\\n'
        '    with st.expander("How the Environment surface works"):\\n',
    ),
)
for _brief_anchor, _brief_replacement in _educational_briefing_insertions:
    _replace_source_once(
        _brief_anchor,
        _brief_replacement,
        "educational briefing insertion point is unavailable",
    )
'''
new_insertion = '''# Put the daily educational brief immediately below the hero on the two
# information surfaces. The original function anchor remains in the replacement so
# the live-fragment decorator can still be installed later in this entrypoint.
_educational_briefing_insertions = (
    (
        "def _render_today() -> None:\\n",
        "def _render_today() -> None:\\n"
        "    render_today_market_brief()\\n\\n",
    ),
    (
        "def _render_environment() -> None:\\n",
        "def _render_environment() -> None:\\n"
        "    render_environment_economic_brief()\\n\\n",
    ),
)
for _brief_anchor, _brief_replacement in _educational_briefing_insertions:
    _replace_source_once(
        _brief_anchor,
        _brief_replacement,
        "educational briefing insertion point is unavailable",
    )
'''
app_source = replace_once(app_source, old_insertion, new_insertion, "app briefing placement")
app_path.write_text(app_source, encoding="utf-8")


brief_path = Path("educational_market_briefing_ui.py")
brief_source = brief_path.read_text(encoding="utf-8")
brief_source = replace_once(
    brief_source,
    "from pathlib import Path\nfrom typing import Any, Iterable, Mapping, Sequence\n",
    "from pathlib import Path\nfrom typing import Any, Iterable, Mapping, Sequence\nfrom zoneinfo import ZoneInfo\n",
    "zoneinfo import",
)
brief_source = replace_once(
    brief_source,
    "_RECENT_WINDOW = timedelta(hours=36)\n",
    "_RECENT_WINDOW = timedelta(hours=24)\n_DAILY_TIMEZONE = ZoneInfo(\"America/Los_Angeles\")\n_DAILY_ROLLOVER_HOUR = 5\n",
    "daily constants",
)
brief_source = replace_once(
    brief_source,
    '''class EducationalBriefingItem:
    title: str
    summary: str
    portfolio_lens: str
    source: str
    source_type: str
    published_at: datetime
    impact_channels: tuple[str, ...]
''',
    '''class EducationalBriefingItem:
    title: str
    summary: str
    portfolio_lens: str
    affected_investments: str
    what_to_watch: str
    source: str
    source_type: str
    published_at: datetime
    impact_channels: tuple[str, ...]
''',
    "briefing item fields",
)
marker = '''class PublicEventSnapshot:
    records: tuple[Mapping[str, Any], ...]
    evaluated_at: datetime | None
    state: str
    detail: str


'''
insert = marker + '''def daily_briefing_date(now: datetime | None = None) -> str:
    """Return the Pacific operating date that rolls at the 5:00 AM CIO cycle."""

    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(_DAILY_TIMEZONE)
    if evaluated_at.hour < _DAILY_ROLLOVER_HOUR:
        evaluated_at -= timedelta(days=1)
    return evaluated_at.date().isoformat()


def _daily_briefing_label(now: datetime | None = None) -> str:
    date_value = datetime.fromisoformat(daily_briefing_date(now))
    return date_value.strftime("%B %d, %Y")


'''
brief_source = replace_once(brief_source, marker, insert, "daily date helpers")

start = brief_source.index("def _portfolio_lens(")
end = brief_source.index("def _to_item(", start)
new_effects = '''def _investment_effects(channels: Sequence[str]) -> tuple[str, str, str]:
    channel_set = set(channels)
    effects: list[str] = []
    affected: list[str] = []
    watch: list[str] = []

    if channel_set & {"policy", "liquidity", "discount_rate", "inflation"}:
        effects.append(
            "Interest-rate expectations can move Treasury prices, borrowing costs, the dollar and the valuations of long-duration equities."
        )
        affected.extend(("cash and short-duration bonds", "Treasuries", "growth equities", "U.S. dollar"))
        watch.extend(("central-bank guidance", "inflation data", "Treasury yields"))
    if channel_set & {"growth", "demand", "earnings"}:
        effects.append(
            "Changes in expected economic activity can alter revenue and profit expectations, especially for cyclical companies and lower-quality credit."
        )
        affected.extend(("cyclical equities", "small caps", "corporate credit", "consumer sectors"))
        watch.extend(("employment", "consumer demand", "earnings guidance"))
    if channel_set & {"credit", "counterparty"}:
        effects.append(
            "A change in credit conditions can widen or narrow spreads and influence banks, leveraged companies and overall risk appetite."
        )
        affected.extend(("corporate bonds", "banks", "high-yield credit", "risk assets"))
        watch.extend(("credit spreads", "defaults", "funding conditions"))
    if channel_set & {"supply", "commodity", "climate_weather"}:
        effects.append(
            "Supply constraints can raise input costs and commodity prices while helping some producers and pressuring industries that consume those inputs."
        )
        affected.extend(("commodities", "energy and materials", "transportation", "inflation-sensitive bonds"))
        watch.extend(("inventories", "shipping", "weather and production updates"))
    if channel_set & {"geopolitical", "regulation", "operational", "cyber"}:
        effects.append(
            "Policy or disruption risk can increase volatility and create sharply different outcomes across directly exposed sectors and regions."
        )
        affected.extend(("defense and energy", "regulated industries", "regional equities", "volatility hedges"))
        watch.extend(("official actions", "company exposure", "market liquidity"))
    if channel_set & {"currency", "volatility", "positioning", "sentiment"}:
        effects.append(
            "Market positioning can amplify price moves even when fundamentals have not changed, affecting diversification and near-term entry risk."
        )
        affected.extend(("currencies", "equity indexes", "volatility strategies", "diversifiers"))
        watch.extend(("currency moves", "volatility", "positioning reversals"))

    effect_text = " ".join(dict.fromkeys(effects))
    affected_text = ", ".join(dict.fromkeys(affected))
    watch_text = ", ".join(dict.fromkeys(watch))
    return (
        effect_text or "The governed CIO process is still resolving the investment relevance of this development.",
        affected_text or "broad portfolio risk",
        watch_text or "corroborating evidence and market response",
    )


def _portfolio_lens(channels: Sequence[str]) -> str:
    effect, _, _ = _investment_effects(channels)
    return effect


def _affected_investments(channels: Sequence[str]) -> str:
    _, affected, _ = _investment_effects(channels)
    return affected


def _what_to_watch(channels: Sequence[str]) -> str:
    _, _, watch = _investment_effects(channels)
    return watch


'''
brief_source = brief_source[:start] + new_effects + brief_source[end:]
brief_source = replace_once(
    brief_source,
    '''        portfolio_lens=_portfolio_lens(channels),
        source=_truncate(provenance.get("provider") or "Public source", limit=80),
''',
    '''        portfolio_lens=_portfolio_lens(channels),
        affected_investments=_affected_investments(channels),
        what_to_watch=_what_to_watch(channels),
        source=_truncate(provenance.get("provider") or "Public source", limit=80),
''',
    "item investment fields",
)

start = brief_source.index("def _overview(")
end = brief_source.index("def economic_snapshot_summary(", start)
new_overview = '''def _overview(items: Sequence[EducationalBriefingItem]) -> str:
    if not items:
        return (
            "No public development in the last 24 hours met the recency, reliability and portfolio-relevance controls. "
            "That is a valid quiet-day result rather than missing content."
        )
    channel_names = [
        channel.replace("_", " ")
        for item in items
        for channel in item.impact_channels
    ]
    common = list(dict.fromkeys(channel_names))[:4]
    channel_text = ", ".join(common) if common else "broad market risk"
    affected = list(dict.fromkeys(item.affected_investments for item in items))
    investment_text = "; ".join(affected[:2])
    return _truncate(
        f"The daily feed identified {len(items)} development{'s' if len(items) != 1 else ''} worth understanding. "
        f"The main transmission channels are {channel_text}. Investments most likely to react include {investment_text}. "
        "The sections below explain what happened, why investors may care, and what evidence to watch next.",
        limit=520,
    )


'''
brief_source = brief_source[:start] + new_overview + brief_source[end:]

start = brief_source.index("def economic_portfolio_lens(")
end = brief_source.index("@st.cache_data", start)
new_economic = '''def economic_investment_implications(
    readings: EconomicReadings | None,
) -> tuple[tuple[str, str], ...]:
    if readings is None:
        return (
            (
                "Rates and cash",
                "Live readings are unavailable, so the app does not infer whether cash, short bonds or long bonds currently have an advantage.",
            ),
            (
                "Equities and credit",
                "Without current growth, inflation and yield evidence, valuation and credit sensitivity remain unresolved.",
            ),
            (
                "What to watch",
                "The next complete inflation, labor, policy and Treasury-yield update will refresh this daily assessment.",
            ),
        )

    policy_gap = readings.federal_funds_rate - readings.inflation_rate
    if policy_gap >= 1.0:
        rates = (
            "The policy rate is meaningfully above inflation. Cash and short-duration bonds may retain attractive income, "
            "while borrowers and highly valued long-duration assets face a higher hurdle."
        )
    elif policy_gap <= -1.0:
        rates = (
            "The policy rate is below inflation. Cash may provide less real purchasing-power protection, increasing the importance of inflation sensitivity and pricing power."
        )
    else:
        rates = (
            "The policy rate is close to inflation. Bond and equity pricing may be especially responsive to the next inflation or central-bank surprise."
        )

    spread = readings.yield_curve_spread
    if spread < -0.10:
        risk_assets = (
            "The 2-year yield is above the 10-year yield, a configuration often associated with restrictive policy or slower-growth concern. "
            "Cyclicals, small caps and lower-quality credit can be more vulnerable if growth weakens."
        )
    elif spread > 0.10:
        risk_assets = (
            "The 10-year yield is above the 2-year yield. Longer bonds offer more term yield, but a rising long rate can pressure growth-stock valuations and rate-sensitive sectors."
        )
    else:
        risk_assets = (
            "The curve is relatively flat. Investors may receive little term compensation while waiting to learn whether growth, inflation or policy moves next."
        )

    labor = (
        f"Unemployment is {readings.unemployment_rate:.1f}%. A sustained rise would usually challenge consumer demand, cyclical earnings and credit quality; "
        "continued labor strength can support spending but also keep wage and inflation pressure relevant."
    )
    return (
        ("Rates, cash and bonds", rates),
        ("Equities and credit", risk_assets),
        ("Growth and consumer sensitivity", labor),
    )


def economic_portfolio_lens(readings: EconomicReadings | None) -> str:
    return " ".join(text for _, text in economic_investment_implications(readings))


'''
brief_source = brief_source[:start] + new_economic + brief_source[end:]

start = brief_source.index("def _render_event_details(")
new_tail = '''def _render_event_details(label: str, items: Sequence[EducationalBriefingItem]) -> None:
    if not items:
        return
    with st.expander(label):
        for index, item in enumerate(items, start=1):
            st.markdown(f"**{index}. {item.title}**")
            st.write(item.summary)
            st.caption(
                f"{item.source_type} source: {item.source} · "
                f"Published {item.published_at.strftime('%b %d · %H:%M UTC')} · "
                f"Most affected: {item.affected_investments}"
            )


def _render_visible_event_cards(items: Sequence[EducationalBriefingItem]) -> None:
    for index, item in enumerate(items, start=1):
        ui.callout_card(
            f"{index}. {item.title}",
            f"What happened: {item.summary} Investment impact: {item.portfolio_lens}",
            f"Most affected: {item.affected_investments} · Watch next: {item.what_to_watch}",
        )
        st.markdown("<div style='height:.55rem'></div>", unsafe_allow_html=True)


def _daily_caption(snapshot: PublicEventSnapshot) -> str:
    freshness = (
        "Unavailable"
        if snapshot.evaluated_at is None
        else snapshot.evaluated_at.strftime("%b %d, %Y · %H:%M UTC")
    )
    return (
        f"Daily briefing for {_daily_briefing_label()} · governed public-event metadata as of {freshness}. "
        "The daily operating date rolls at 5:00 AM Pacific and the source file is re-read as new governed records arrive."
    )


def render_today_market_brief() -> None:
    snapshot = load_public_event_snapshot()
    items = build_today_items(snapshot.records)
    ui.page_header(
        "What's happening today",
        "A concise daily investment briefing: what happened, why investors may care, which investments may react, and what to watch next.",
        "NOW",
    )
    ui.text_card("Daily investment synopsis", _overview(items))
    if items:
        _render_visible_event_cards(items)
        _render_event_details("Sources and supporting event detail", items)
    else:
        st.caption(snapshot.detail)
    st.caption(
        _daily_caption(snapshot)
        + " Educational context only; this section does not alter the CIO conclusion or authorize a paper trade."
    )


def render_environment_economic_brief() -> None:
    snapshot = load_public_event_snapshot()
    items = build_economic_event_items(snapshot.records)
    dashboard = load_dashboard_data()
    ui.page_header(
        "Economic context today",
        "The daily economic picture and a direct explanation of how rates, inflation, growth and the yield curve can affect investments.",
        "ECON",
    )
    ui.text_card("Economic picture", economic_snapshot_summary(dashboard.readings))
    for title, explanation in economic_investment_implications(dashboard.readings):
        ui.callout_card(title, explanation)
        st.markdown("<div style='height:.55rem'></div>", unsafe_allow_html=True)
    if items:
        ui.page_header(
            "Economic developments affecting investments",
            "Recent economic and policy events with their likely investment transmission channels stated plainly.",
            "WATCH",
        )
        _render_visible_event_cards(items)
        _render_event_details("Sources and supporting economic detail", items)
    else:
        st.caption(snapshot.detail)
    st.caption(
        _daily_caption(snapshot)
        + f" Economic readings: {dashboard.data_source}. Educational interpretation only; "
        "the governed CIO process separately determines whether any portfolio action is justified."
    )
'''
brief_source = brief_source[:start] + new_tail
brief_path.write_text(brief_source, encoding="utf-8")


test_path = Path("tests/test_educational_market_briefing.py")
test_source = test_path.read_text(encoding="utf-8")
test_source = replace_once(
    test_source,
    '''    build_today_items,
    economic_portfolio_lens,
    economic_snapshot_summary,
''',
    '''    build_today_items,
    daily_briefing_date,
    economic_investment_implications,
    economic_portfolio_lens,
    economic_snapshot_summary,
''',
    "test imports",
)
test_source = replace_once(
    test_source,
    '''    assert all("OFAC sanctions listing" not in item.title for item in items)
    assert "Rates, bond prices" in items[0].portfolio_lens
''',
    '''    assert all("OFAC sanctions listing" not in item.title for item in items)
    assert "Interest-rate expectations" in items[0].portfolio_lens
    assert "Treasuries" in items[0].affected_investments
    assert "central-bank guidance" in items[0].what_to_watch
''',
    "today impact assertions",
)
test_source = replace_once(
    test_source,
    '''    assert "cash and short-duration bonds" in lens
    assert "cyclical earnings" in lens
''',
    '''    assert "Cash and short-duration bonds" in lens
    assert "Cyclicals, small caps" in lens
    implications = economic_investment_implications(readings)
    assert [title for title, _ in implications] == [
        "Rates, cash and bonds",
        "Equities and credit",
        "Growth and consumer sensitivity",
    ]
''',
    "economic implication assertions",
)
test_source = replace_once(
    test_source,
    '''    assert "educational briefing insertion point is unavailable" in source
''',
    '''    assert "educational briefing insertion point is unavailable" in source
    today_anchor = '\"def _render_today() -> None:\\\\n\"'
    environment_anchor = '\"def _render_environment() -> None:\\\\n\"'
    assert today_anchor in source
    assert environment_anchor in source
    assert source.index(today_anchor) < source.index('# Refresh the active operating surface')
''',
    "placement assertions",
)
test_source += '''\n\ndef test_daily_briefing_operating_date_rolls_at_five_pacific() -> None:\n    before = datetime(2026, 7, 30, 11, 59, tzinfo=timezone.utc)\n    after = datetime(2026, 7, 30, 12, 1, tzinfo=timezone.utc)\n\n    assert daily_briefing_date(before) == "2026-07-29"\n    assert daily_briefing_date(after) == "2026-07-30"\n\n\ndef test_visible_copy_explains_investment_effect_and_daily_refresh() -> None:\n    source = Path("educational_market_briefing_ui.py").read_text(encoding="utf-8")\n\n    assert "What happened:" in source\n    assert "Investment impact:" in source\n    assert "Most affected:" in source\n    assert "Watch next:" in source\n    assert "rolls at 5:00 AM Pacific" in source\n'''
test_path.write_text(test_source, encoding="utf-8")

for path in (app_path, brief_path, test_path):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
