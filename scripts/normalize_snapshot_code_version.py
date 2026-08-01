from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "opportunity/snapshot.py"
text = path.read_text(encoding="utf-8")
old = '''        value
        or os.getenv("CAPITAL_INTELLIGENCE_CODE_VERSION")
        or os.getenv("GITHUB_SHA")
        or "unknown",
'''
new = '''        value
        or os.getenv("CAPITAL_INTELLIGENCE_CODE_VERSION")
        or os.getenv("RENDER_GIT_COMMIT")
        or "unknown",
'''
if text.count(old) != 1:
    raise RuntimeError("expected one snapshot code-version resolver")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
