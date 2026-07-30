from __future__ import annotations

from pathlib import Path

patch_path = Path("scripts/apply_operating_completeness_fix.py")
text = patch_path.read_text(encoding="utf-8")
start_marker = '''insert_once(
    "historical_replay_ui.py",
    ''' + "'''def render_canonical_historical_replay() -> None:\n''',\n"
start = text.index(start_marker)
helper_marker = "'''def historical_macro_certification_detail"
helper_start = text.index(helper_marker, start)
end_marker = "''',\n)\nreplace_once(\n    \"historical_replay_ui.py\","
helper_end = text.index(end_marker, helper_start)
helper_source = text[helper_start + 3 : helper_end]
replacement = (
    "replace_once(\n"
    "    \"historical_replay_ui.py\",\n"
    "    '''def render_canonical_historical_replay() -> None:\\n''',\n"
    "    '''"
    + helper_source
    + "def render_canonical_historical_replay() -> None:\\n''',\n"
    ")\n"
)
text = text[:start] + replacement + text[helper_end + len("''',\n)\n") :]
patch_path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
