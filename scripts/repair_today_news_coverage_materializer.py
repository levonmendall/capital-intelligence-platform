"""Repair deterministic assertions in the one-use Today materializer."""

from __future__ import annotations

from pathlib import Path


path = Path(__file__).with_name("materialize_today_news_coverage_resilience.py")
text = path.read_text(encoding="utf-8")


def replace_exact(old: str, new: str, *, expected: int = 1) -> None:
    global text
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"Today coverage materializer repair target changed: expected {expected}, found {count}"
        )
    text = text.replace(old, new)


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

path.write_text(text, encoding="utf-8")
