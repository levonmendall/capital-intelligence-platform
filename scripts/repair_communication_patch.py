from pathlib import Path

patch = Path("scripts/expose_daily_cio_briefing.py")
text = patch.read_text(encoding="utf-8")
replacements = (
    (
        '    "# Keep the execution worker alive on every Streamlit surface.\\n",\n',
        '    "# Keep the execution worker alive on every Streamlit surface. It consumes only an\\n",\n',
    ),
    (
        '            "Live market and macro evidence is available",\n',
        '            "Live environment evidence is available",\n',
    ),
    (
        '            "No separate regime label has been synthesized from those readings."\n',
        '            "Regime: Not separately classified. No synthetic label is inferred from those readings."\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise RuntimeError(f"communication patch repair is unavailable: {old!r}")
    text = text.replace(old, new, 1)
patch.write_text(text, encoding="utf-8")
Path(__file__).unlink()
