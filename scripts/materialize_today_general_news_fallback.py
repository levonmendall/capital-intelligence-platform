"""Allow current source-qualified news through the investor-facing Today adapter."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "today_event_alignment_runtime.py"
text = PATH.read_text(encoding="utf-8")

old_fallback = '''    # Other public records are also withheld when the text does not establish a
    # specific transmission channel. A truthful quiet-day state is preferable to
    # a generic all-markets paragraph.
    return None
'''
new_fallback = '''    # Today is an awareness and education surface, not the CIO evidence gate.
    # A current source-qualified development should remain visible even when its
    # exact transmission channel has not yet been established. Keep the language
    # neutral rather than suppressing the headline or inventing a directional view.
    source_type = _source_type(record).lower()
    if source_type not in {
        "official",
        "regulatory",
        "issuer",
        "newswire",
        "journalism",
        "research",
        "market",
        "alternative",
    }:
        return None
    what_happened = (
        summary
        if summary and summary.lower() != title.lower()
        else f"A current public source reported: {title}."
    )
    return EventInterpretation(
        what_happened=what_happened,
        why_it_matters=(
            "The development is current and source-qualified. Its precise portfolio "
            "transmission is not yet specific enough for a directional conclusion, but "
            "it may still affect expectations, prices, or risk sentiment."
        ),
        market_reaction=(
            "Treat the market effect as unresolved until price action, official "
            "confirmation, or identifiable issuer and sector exposure establishes the "
            "transmission channel."
        ),
        exposure=(
            "the issuers, sectors, regions, commodities, currencies, or asset classes "
            "directly named in the development"
        ),
        what_to_watch=(
            "official confirmation, affected-asset price moves, issuer exposure, and "
            "independent follow-up reporting"
        ),
        channels=("sentiment",),
        lesson_title="Headline awareness versus investment evidence",
        lesson_copy=(
            "A headline can be worth knowing before it is strong enough to support a "
            "portfolio conclusion. The Today page keeps that distinction visible: report "
            "the development, explain what remains unresolved, and wait for evidence before "
            "inferring direction."
        ),
        priority=0.18,
    )
'''
if text.count(old_fallback) != 1:
    raise RuntimeError("generic Today fallback target changed")
text = text.replace(old_fallback, new_fallback, 1)

old_admission = '''        title = _clean(raw.get("topic"))
        summary = _clean(raw.get("summary"))
        published_at = event_ui._record_time(raw)
        if not title or not summary or published_at is None:
            continue
'''
new_admission = '''        title = _clean(raw.get("topic"))
        summary = _clean(raw.get("summary")) or title
        published_at = event_ui._record_time(raw)
        if not title or published_at is None:
            continue
'''
if text.count(old_admission) != 1:
    raise RuntimeError("Today aligned-builder admission target changed")
text = text.replace(old_admission, new_admission, 1)
PATH.write_text(text, encoding="utf-8")
