from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import educational_market_briefing_ui as event_ui
import environment_story_placement_refinement as story
import operating_intelligence_ui as operating_ui
import public_event_recency_runtime
import today_development_card_format_runtime as card_format
import today_event_alignment_runtime as alignment


_BROAD_FEDERAL_REGISTER_CHANNELS = (
    "policy",
    "earnings",
    "credit",
    "regulation",
    "geopolitical",
    "operational",
    "volatility",
)


def _record(
    *,
    identifier: str,
    title: str,
    summary: str,
    published_at: datetime,
) -> dict[str, object]:
    timestamp = published_at.isoformat()
    return {
        "identifier": identifier,
        "canonical_event_identifier": identifier,
        "topic": title,
        "summary": summary,
        "event_at": timestamp,
        "published_at": timestamp,
        "available_at": timestamp,
        "impact_channels": list(_BROAD_FEDERAL_REGISTER_CHANNELS),
        "tags": ["federal-register-document"],
        "reliability": 0.99,
        "relevance": 0.9,
        "materiality": 0.75,
        "independence": 1.0,
        "provenance": {
            "provider": "Federal Register document API",
            "source_type": "official",
        },
    }


def _install() -> None:
    public_event_recency_runtime.install(event_ui)
    alignment.install(event_ui, operating_ui, story)
    card_format.install(story)


def test_routine_meeting_notice_is_not_presented_as_a_market_event() -> None:
    now = datetime(2026, 8, 2, 22, 0, tzinfo=timezone.utc)
    meeting = _record(
        identifier="niaid-meeting",
        title="National Institute of Allergy and Infectious Diseases; Notice of Meetings",
        summary="National Institute of Allergy and Infectious Diseases; Notice of Meetings",
        published_at=now - timedelta(minutes=30),
    )
    _install()

    assert alignment.build_today_items((meeting,), now=now) == ()


def test_federal_register_events_receive_specific_explanations() -> None:
    now = datetime(2026, 8, 2, 22, 0, tzinfo=timezone.utc)
    meeting = _record(
        identifier="niaid-meeting",
        title="National Institute of Allergy and Infectious Diseases; Notice of Meetings",
        summary="National Institute of Allergy and Infectious Diseases; Notice of Meetings",
        published_at=now - timedelta(minutes=30),
    )
    nextera = _record(
        identifier="nextera-duane-arnold",
        title=(
            "NextEra Energy Duane Arnold, LLC; Duane Arnold Energy Center; Draft "
            "Environmental Assessment and Draft Finding of No Significant Impact"
        ),
        summary=(
            "The U.S. Nuclear Regulatory Commission is issuing for public comment a "
            "draft environmental assessment and draft finding of no significant impact."
        ),
        published_at=now - timedelta(minutes=28),
    )
    cboe = _record(
        identifier="cboe-trust-shares",
        title=(
            "Self-Regulatory Organizations; Cboe BZX Exchange, Inc.; Notice of Filing, "
            "and Order Granting Accelerated Approval of a Proposed Rule Change To Amend "
            "Rule 14.11(e)(4) (Commodity-Based Trust Shares)"
        ),
        summary=(
            "Self-Regulatory Organizations; Cboe BZX Exchange, Inc.; Notice of Filing, "
            "and Order Granting Accelerated Approval of a Proposed Rule Change To Amend "
            "Rule 14.11(e)(4) (Commodity-Based Trust Shares)"
        ),
        published_at=now - timedelta(minutes=26),
    )
    _install()

    items = alignment.build_today_items(
        (meeting, nextera, cboe),
        now=now,
        limit=5,
    )
    by_title = {item.title: item for item in items}

    assert all("Allergy and Infectious Diseases" not in title for title in by_title)
    nextera_item = next(item for item in items if "Duane Arnold" in item.title)
    cboe_item = next(item for item in items if "Cboe BZX" in item.title)

    assert "project- and issuer-specific" in nextera_item.why_it_matters
    assert "NextEra-related valuation" in nextera_item.portfolio_lens
    assert "Treasury prices" not in nextera_item.portfolio_lens
    assert "licensing decision" in nextera_item.what_to_watch

    assert "specific exchange-traded product" in cboe_item.why_it_matters
    assert "affected product" in cboe_item.portfolio_lens
    assert "Treasury prices" not in cboe_item.portfolio_lens
    assert "market_structure" in cboe_item.impact_channels


def test_repeated_all_asset_block_and_repeated_lesson_are_removed() -> None:
    now = datetime(2026, 8, 2, 22, 0, tzinfo=timezone.utc)
    cboe = _record(
        identifier="cboe-trust-shares",
        title=(
            "Self-Regulatory Organizations; Cboe BZX Exchange, Inc.; Notice of Filing, "
            "and Order Granting Accelerated Approval of a Proposed Rule Change To Amend "
            "Rule 14.11(e)(4) (Commodity-Based Trust Shares)"
        ),
        summary=(
            "Self-Regulatory Organizations; Cboe BZX Exchange, Inc.; Notice of Filing, "
            "and Order Granting Accelerated Approval of a Proposed Rule Change To Amend "
            "Rule 14.11(e)(4) (Commodity-Based Trust Shares)"
        ),
        published_at=now - timedelta(minutes=26),
    )
    _install()
    item = alignment.build_today_items((cboe,), now=now)[0]

    primary = story._primary(item)
    secondary = story._secondary(item, 2)
    tags = story._tags(item)
    combined = primary + secondary + tags

    assert "cash and short-duration bonds" not in combined
    assert "consumer sectors" not in combined
    assert "volatility strategies" not in combined
    assert "Most directly exposed:" in primary
    assert "Investor lesson" not in secondary
    assert '<div class="ci-label">Why it matters</div>' in secondary
    assert '<div class="ci-label">How markets may react</div>' in secondary


def test_active_entrypoints_install_event_alignment() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import today_event_alignment_runtime" in source
        assert "today_event_alignment_runtime.install" in source
