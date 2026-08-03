"""Make the Today coverage regression independent of pytest import order."""

from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tests/test_today_news_coverage_resilience.py"
text = path.read_text(encoding="utf-8")

old_import = '''import educational_market_briefing_ui as event_ui
import today_story_retention_runtime as retention
'''
new_import = '''import educational_market_briefing_ui as event_ui
import today_event_alignment_runtime as alignment
import today_story_retention_runtime as retention
'''
if text.count(old_import) != 1:
    raise RuntimeError("Today coverage regression import target changed")
text = text.replace(old_import, new_import, 1)

old_call = '''    items = event_ui.build_today_items((_record("broad", now - timedelta(hours=1)),), now=now)
'''
new_call = '''    items = alignment.build_today_items((_record("broad", now - timedelta(hours=1)),), now=now)
'''
if text.count(old_call) != 1:
    raise RuntimeError("Today coverage regression builder target changed")
text = text.replace(old_call, new_call, 1)

path.write_text(text, encoding="utf-8")
