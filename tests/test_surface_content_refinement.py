from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import surface_content_refinement as refinement


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdown_values: list[str] = []
        self.caption_values: list[str] = []
        self.write_values: list[object] = []
        self.expander_labels: list[str] = []

    def markdown(self, value: str, **_kwargs: object) -> None:
        self.markdown_values.append(value)

    def caption(self, value: str) -> None:
        self.caption_values.append(value)

    def write(self, value: object) -> None:
        self.write_values.append(value)

    def divider(self) -> None:
        return None

    @contextmanager
    def expander(self, label: str, **_kwargs: object):
        self.expander_labels.append(label)
        yield

    def fragment(self, **_kwargs: object):
        def decorate(function):
            function.__wrapped__ = function
            return function

        return decorate


def _event(*, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        title="Policy guidance changed the rate outlook",
        summary="The central bank signaled that restrictive policy may last longer.",
        portfolio_lens=(
            "Higher expected rates can lift bond yields, pressure long-duration equities, "
            "and support the dollar."
        ),
        affected_investments="Treasuries, growth equities, banks, and the U.S. dollar",
        impact_channels=("policy", "discount_rate", "liquidity"),
        what_to_watch="Inflation data, Treasury yields, and central-bank guidance",
        source="Official central bank",
        source_type="Official",
        published_at=now - timedelta(hours=2),
    )


def _patch_shared(monkeypatch, fake: _FakeStreamlit) -> None:
    monkeypatch.setattr(refinement, "st", fake)
    monkeypatch.setattr(
        refinement.concise.base,
        "_daily_caption",
        lambda _snapshot: "Operating briefing.",
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "_matching_record",
        lambda _item, _records: None,
    )


def test_today_explains_fact_importance_and_market_transmission_without_portfolio_duplication(
    monkeypatch,
) -> None:
    fake = _FakeStreamlit()
    _patch_shared(monkeypatch, fake)
    now = datetime(2026, 8, 2, 3, 0, tzinfo=timezone.utc)
    item = _event(now=now)
    snapshot = SimpleNamespace(
        records=({},),
        detail="Current source-qualified event record.",
        evaluated_at=now - timedelta(minutes=5),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_public_event_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "build_today_items",
        lambda _records, limit=3: (item,),
    )

    refinement.render_today_market_brief(
        briefing={"portfolio_decision": "hold"},
        live_market={
            "market_open": False,
            "quote_count": 15,
            "expected_quote_count": 15,
        },
    )

    markup = "\n".join(fake.markdown_values)
    assert 'class="today-editorial"' in markup
    assert "What happened" in markup
    assert "Why it matters" in markup
    assert "How markets may react" in markup
    assert "What to watch next" in markup
    assert "Investor lesson" in markup
    assert "Discount rates" in markup
    assert "ranked by recency, reliability and materiality" in markup
    assert "Official central bank" in markup
    assert "CIO response" not in markup
    assert "Portfolio effect" not in markup
    assert "Portfolio value" not in markup
    assert "Available cash" not in markup
    assert fake.expander_labels == ["Original sources and full event context"]


def test_today_quiet_day_does_not_fill_the_page_with_low_quality_headlines(
    monkeypatch,
) -> None:
    fake = _FakeStreamlit()
    _patch_shared(monkeypatch, fake)
    now = datetime(2026, 8, 2, 3, 0, tzinfo=timezone.utc)
    snapshot = SimpleNamespace(
        records=(),
        detail="No source passed the relevance controls.",
        evaluated_at=now,
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_public_event_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "build_today_items",
        lambda _records, limit=3: (),
    )

    refinement.render_today_market_brief(
        live_market={"market_open": False, "quote_count": 0, "expected_quote_count": 15}
    )

    markup = "\n".join(fake.markdown_values)
    assert "Quiet-day conclusion" in markup
    assert "No new story earned investor attention" in markup
    assert "low-quality or repetitive headlines" in markup


def test_environment_uses_four_structural_drivers_and_cross_asset_map(
    monkeypatch,
) -> None:
    fake = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake)
    evaluated_at = datetime(2026, 8, 2, 2, 50, tzinfo=timezone.utc)
    readings = SimpleNamespace(
        inflation_rate=2.6,
        unemployment_rate=4.2,
        federal_funds_rate=4.5,
        yield_curve_spread=0.35,
        evaluated_at=evaluated_at,
    )
    dashboard = SimpleNamespace(
        readings=readings,
        data_source="Live FRED data",
        status="Connected",
        snapshot=SimpleNamespace(
            growth=0.3,
            inflation=0.15,
            credit=-0.1,
            volatility=0.2,
        ),
    )
    environment = {
        "regime": "Moderating inflation with resilient growth",
        "headline": "Growth remains positive while inflation pressure is easing.",
        "summary": "Rates remain restrictive and liquidity is mixed.",
        "review_conditions": [
            "A renewed rise in inflation",
            "A material weakening in labor demand",
        ],
    }
    monkeypatch.setattr(
        refinement.concise.base,
        "economic_snapshot_summary",
        lambda _readings: "Inflation is moderating while labor demand remains firm.",
    )

    refinement.render_environment_economic_brief(
        briefing={"portfolio_decision": "hold"},
        environment=environment,
        dashboard=dashboard,
        live_market={
            "status": "connected",
            "market_open": False,
            "quote_count": 15,
            "expected_quote_count": 15,
        },
    )

    markup = "\n".join(fake.markdown_values)
    assert 'class="environment-dashboard"' in markup
    for label in ("Growth", "Inflation", "Rates", "Liquidity"):
        assert f'>{label}<' in markup
    assert "Why markets care" in markup
    assert "Most sensitive" in markup
    assert "How this backdrop reaches markets" in markup
    for market in ("Equities", "Bonds", "Credit", "Dollar &amp; commodities"):
        assert market in markup
    assert "Read the economy through four channels" in markup
    assert "Conditions that deserve the next review" in markup
    assert "CIO response" not in markup
    assert "Portfolio effect" not in markup
    assert "What happened" not in markup


def test_age_label_is_plain_and_current() -> None:
    now = datetime(2026, 8, 2, 3, 0, tzinfo=timezone.utc)
    assert refinement._age_label(now - timedelta(seconds=30), now=now) == "just verified"
    assert refinement._age_label(now - timedelta(minutes=17), now=now) == "verified 17m ago"
    assert refinement._age_label(now - timedelta(hours=4), now=now) == "verified 4h ago"


def test_source_health_is_filtered_to_the_active_surface(monkeypatch) -> None:
    fake = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake)
    entries = (
        SimpleNamespace(label="Market quotes", state="Current", detail="Quotes"),
        SimpleNamespace(label="Economic data", state="Current", detail="Macro"),
        SimpleNamespace(label="Public events", state="Current", detail="Events"),
        SimpleNamespace(label="CIO conclusion", state="Current", detail="CIO"),
        SimpleNamespace(label="Portfolio valuation", state="Current", detail="NAV"),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_live_market_console",
        lambda: {},
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_dashboard_data",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_public_event_snapshot",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "get_mandate_details",
        lambda _code: {},
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "build_freshness_entries",
        lambda **_kwargs: entries,
    )
    monkeypatch.setattr(
        refinement.experience,
        "_freshness_tone",
        lambda _entries: ("current", "Current"),
    )
    monkeypatch.setattr(
        refinement.experience,
        "_freshness_summary",
        lambda selected: ", ".join(item.label for item in selected),
    )
    captured: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        refinement.concise.ui,
        "metric_grid",
        lambda metrics, **_kwargs: captured.append(
            tuple(str(label) for label, _value, _detail in metrics)
        ),
    )

    refinement.render_information_freshness(briefing=None, surface="today")
    refinement.render_information_freshness(briefing=None, surface="environment")
    refinement.render_information_freshness(briefing=None, surface="portfolio")

    assert captured == [
        ("Market quotes", "Public events"),
        ("Market quotes", "Economic data"),
        ("CIO conclusion", "Portfolio valuation"),
    ]


def test_install_changes_today_and_environment_but_preserves_other_surfaces(
    monkeypatch,
) -> None:
    fake = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake)
    original_today = object()
    original_environment = object()
    original_portfolio = object()
    original_history = object()
    app = SimpleNamespace(
        render_information_freshness=object(),
        render_today_market_brief=object(),
        render_environment_economic_brief=object(),
        _render_today=original_today,
        _render_environment=original_environment,
        _render_portfolio=original_portfolio,
        _render_history=original_history,
    )

    refinement.install(app)

    assert app._render_today is not original_today
    assert app._render_environment is not original_environment
    assert app._render_portfolio is original_portfolio
    assert app._render_history is original_history
    assert app.render_today_market_brief is refinement.render_today_market_brief
    assert (
        app.render_environment_economic_brief
        is refinement.render_environment_economic_brief
    )
