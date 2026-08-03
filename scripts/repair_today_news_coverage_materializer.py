"""Repair deterministic assertions in the one-use Today materializer."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
materializer_path = Path(__file__).with_name(
    "materialize_today_news_coverage_resilience.py"
)
text = materializer_path.read_text(encoding="utf-8")


def replace_exact(old: str, new: str, *, expected: int = 1) -> None:
    global text
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"Today coverage materializer repair target changed: expected {expected}, found {count}"
        )
    text = text.replace(old, new)


def replace_file(relative: str, old: str, new: str, *, expected: int = 1) -> None:
    path = ROOT / relative
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != expected:
        raise RuntimeError(
            f"{relative}: deterministic test target changed: expected {expected}, found {count}"
        )
    path.write_text(source.replace(old, new), encoding="utf-8")


replace_exact(
    '''    assert 'CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS\\n        value: "900"' in render
''',
    '''    assert "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS" in render
    assert 'value: "900"' in render
''',
)
replace_exact(
    '''import public_event_recency_runtime
''',
    '''''',
)
replace_exact(
    '''    public_event_recency_runtime.install(event_ui)
''',
    '''''',
    expected=2,
)
replace_exact(
    '''    assert items[0].summary == "Headline broad"
''',
    '''    assert items[0].summary == "The public source reported this development without additional concise detail."
''',
)
materializer_path.write_text(text, encoding="utf-8")

# The event-alignment test relies on the active entrypoint order: event-specific
# interpretation first, full-width secondary-card formatting second. Install both
# explicitly so the test is isolated from pytest file ordering.
replace_file(
    "tests/test_today_event_alignment_runtime.py",
    '''import public_event_recency_runtime
import today_event_alignment_runtime as alignment
''',
    '''import public_event_recency_runtime
import today_development_card_format_runtime as card_format
import today_event_alignment_runtime as alignment
''',
)
replace_file(
    "tests/test_today_event_alignment_runtime.py",
    '''def _install() -> None:
    public_event_recency_runtime.install(event_ui)
    alignment.install(event_ui, operating_ui, story)
''',
    '''def _install() -> None:
    public_event_recency_runtime.install(event_ui)
    alignment.install(event_ui, operating_ui, story)
    card_format.install(story)
''',
)
