from pathlib import Path

path = Path("reporting/daily_cio.py")
source = path.read_text(encoding="utf-8")
old = '''            evidence_limited_terms = (
                "evidence",
                "data",
                "stale",
                "missing",
                "incomplete",
                "coverage",
                "unavailable",
                "uncertified",
                "unapproved",
            )
'''
new = '''            evidence_limited_terms = (
                "insufficient evidence",
                "evidence quality",
                "stale data",
                "data is stale",
                "missing",
                "incomplete",
                "analytical coverage",
                "coverage is below",
                "unavailable",
                "uncertified",
                "unapproved",
            )
'''
if source.count(old) != 1:
    raise RuntimeError(f"expected one evidence classification block, found {source.count(old)}")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
