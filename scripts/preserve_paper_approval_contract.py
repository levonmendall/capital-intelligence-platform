from pathlib import Path

path = Path("app.py")
text = path.read_text(encoding="utf-8")
old = 'raise RuntimeError("Portfolio paper control insertion point is unavailable")'
new = 'raise RuntimeError("paper decision approval insertion point is unavailable")'
if text.count(old) != 1:
    raise RuntimeError("paper approval compatibility string is unavailable")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
Path(__file__).unlink()
