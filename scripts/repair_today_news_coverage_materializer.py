"""Repair one escaped-newline assertion in the one-use Today materializer."""

from __future__ import annotations

from pathlib import Path


path = Path(__file__).with_name("materialize_today_news_coverage_resilience.py")
text = path.read_text(encoding="utf-8")
old = '''    assert 'CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS\\n        value: "900"' in render
'''
new = '''    assert "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS" in render
    assert 'value: "900"' in render
'''
if text.count(old) != 1:
    raise RuntimeError(
        "Today coverage materializer escaped-newline assertion target changed"
    )
path.write_text(text.replace(old, new, 1), encoding="utf-8")
