from pathlib import Path

patch = Path("scripts/expose_daily_cio_briefing.py")
text = patch.read_text(encoding="utf-8")
old = '    "# Keep the execution worker alive on every Streamlit surface.\\n",\n'
new = '    "# Keep the execution worker alive on every Streamlit surface. It consumes only an\\n",\n'
if text.count(old) != 1:
    raise RuntimeError("communication patch end marker repair is unavailable")
patch.write_text(text.replace(old, new, 1), encoding="utf-8")
Path(__file__).unlink()
