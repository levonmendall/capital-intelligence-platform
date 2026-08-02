from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import environment_story_placement_refinement as story
import today_development_card_format_runtime as card_format
import today_event_alignment_runtime as alignment


def _item() -> SimpleNamespace:
    return SimpleNamespace(
        title="Example market-structure development",
        summary="A specific rule change was approved for the named clearing venue.",
        why_it_matters="The change may alter clearing access, collateral, or transaction costs.",
        portfolio_lens="Reaction should remain concentrated in the affected venue and products.",
        affected_investments="the clearing venue, affected credit products, and direct participants",
        source="Federal Register document API",
        source_type="Official",
        published_at=datetime(2026, 8, 2, 22, 30, tzinfo=timezone.utc),
        impact_channels=("regulation", "market_structure", "liquidity"),
        lesson_title="Market structure",
        lesson_copy="Market plumbing matters when it changes access, cost, or risk transfer.",
    )


def test_secondary_development_uses_lead_story_structure() -> None:
    alignment.install(story=story)
    card_format.install(story)

    markup = story._secondary(_item(), 2)

    assert 'class="ci-story ci-story-feature"' in markup
    assert 'class="ci-title"' in markup
    assert markup.count('class="ci-box"') == 3
    assert '<div class="ci-label">What happened</div>' in markup
    assert '<div class="ci-label">Why it matters</div>' in markup
    assert '<div class="ci-label">How markets may react</div>' in markup
    assert "Development 02" in markup
    assert "Official · Federal Register document API" in markup
    assert "Most directly exposed:" in markup
    assert "<strong>What happened:</strong>" not in markup


def test_secondary_developments_are_full_width_and_mobile_safe() -> None:
    source = Path("today_development_card_format_runtime.py").read_text(
        encoding="utf-8"
    )

    assert ".ci-story-grid{grid-template-columns:1fr" in source
    assert "@media(max-width:720px)" in source
    assert ".ci-story-feature .ci-three" in source


def test_active_entrypoints_install_card_format_after_event_alignment() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import today_development_card_format_runtime" in source
        alignment_index = source.index("today_event_alignment_runtime.install")
        format_index = source.index("today_development_card_format_runtime.install")
        assert alignment_index < format_index
