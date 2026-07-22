
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent

def load_settings():
    env = ROOT / ".env"
    if env.exists():
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    try:
        import streamlit as st
        for key in ("FRED_API_KEY", "APP_PASSWORD", "APP_TITLE"):
            if key in st.secrets and str(st.secrets[key]).strip():
                os.environ[key] = str(st.secrets[key]).strip()
    except Exception:
        pass

load_settings()
