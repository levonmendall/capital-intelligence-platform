"""Premium, restrained Streamlit presentation helpers for Capital Intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Iterable

import pandas as pd
import streamlit as st


APP_SUBTITLE = (
    "Institutional market intelligence for one governed portfolio, expressed "
    "with clarity and restraint."
)


def format_currency(value: float) -> str:
    return f"${float(value):,.2f}"


def format_percent(value: float) -> str:
    return f"{float(value):+.2%}"


def format_datetime(value: object) -> str:
    if value in (None, ""):
        return "—"
    try:
        parsed = pd.to_datetime(value, utc=True)
    except Exception:
        return str(value)
    return parsed.strftime("%b %d, %Y · %H:%M UTC")


def apply_global_style() -> None:
    st.markdown(
        """
        <style>
        :root{--ink:#0b1220;--muted:#64748b;--blue:#2563eb;--line:rgba(15,23,42,.08)}
        #MainMenu,footer,[data-testid="stToolbar"]{visibility:hidden}
        [data-testid="stHeader"]{background:transparent}
        .stApp{background:radial-gradient(circle at 85% 0%,rgba(37,99,235,.07),transparent 28rem),linear-gradient(180deg,#f5f7fb 0%,#f8fafc 100%)}
        .block-container{max-width:1280px;padding-top:1.4rem;padding-bottom:2.5rem}
        [data-testid="stSidebar"]{background:linear-gradient(180deg,#0f172a 0%,#111827 100%);border-right:1px solid rgba(255,255,255,.06)}
        [data-testid="stSidebar"] *{color:#e5e7eb}
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#cbd5e1}
        .sidebar-brand{padding:1.05rem 1rem 1rem;border:1px solid rgba(255,255,255,.09);border-radius:20px;background:linear-gradient(145deg,rgba(255,255,255,.07),rgba(255,255,255,.025));box-shadow:inset 0 1px 0 rgba(255,255,255,.04);margin-bottom:1rem}
        .sidebar-mark{width:2.35rem;height:2.35rem;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,#3b82f6,#1d4ed8);color:white;font-size:.76rem;font-weight:800;letter-spacing:.08em;margin-bottom:.8rem;box-shadow:0 10px 24px rgba(37,99,235,.28)}
        .sidebar-brand-title{font-size:1rem;font-weight:700;color:#fff;margin-bottom:.2rem}
        .sidebar-brand-copy{font-size:.88rem;line-height:1.4;color:#cbd5e1}
        .hero-card{position:relative;overflow:hidden;background:linear-gradient(135deg,rgba(255,255,255,.98),rgba(248,251,255,.96));border:1px solid rgba(15,23,42,.075);border-radius:28px;padding:1.55rem 1.6rem 1.35rem;box-shadow:0 18px 45px rgba(15,23,42,.07);margin-bottom:1.1rem}
        .hero-card:after{content:"";position:absolute;width:18rem;height:18rem;right:-8rem;top:-11rem;border-radius:999px;background:radial-gradient(circle,rgba(37,99,235,.13),rgba(37,99,235,0));pointer-events:none}
        .hero-grid{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1.5rem;align-items:start;position:relative;z-index:1}
        .hero-monogram{width:4.2rem;height:4.2rem;border-radius:20px;display:grid;place-items:center;background:linear-gradient(145deg,#0f172a,#1e293b);color:#fff;font-size:.9rem;font-weight:800;letter-spacing:.12em;box-shadow:0 16px 32px rgba(15,23,42,.18)}
        .hero-eyebrow{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#2563eb;margin-bottom:.65rem}
        .hero-title{font-size:1.9rem;line-height:1.1;font-weight:800;color:#0f172a;margin:0}
        .hero-copy{font-size:.98rem;line-height:1.55;color:#475569;margin:.6rem 0 0}
        .hero-meta{margin-top:.85rem;display:flex;flex-wrap:wrap;gap:.5rem}
        .page-chip{display:inline-flex;align-items:center;padding:.38rem .72rem;border-radius:999px;font-size:.78rem;font-weight:600;border:1px solid var(--line);background:#f8fafc;color:#334155}
        .page-chip.primary{background:rgba(37,99,235,.1);color:#1d4ed8;border-color:rgba(37,99,235,.16)}
        .section-card{background:#fff;border:1px solid var(--line);border-radius:22px;padding:1.1rem 1.1rem .95rem;box-shadow:0 10px 24px rgba(15,23,42,.04);height:100%}
        .section-title{font-size:1rem;font-weight:700;color:#0f172a;margin-bottom:.45rem}
        .section-copy{font-size:.95rem;line-height:1.58;color:#475569;margin:0}
        .callout-card{background:linear-gradient(135deg,rgba(37,99,235,.08),rgba(14,165,233,.06));border:1px solid rgba(37,99,235,.1);border-radius:22px;padding:1.1rem 1.1rem 1rem;margin-top:.2rem}
        .callout-title{font-size:.88rem;font-weight:700;color:#1d4ed8;text-transform:uppercase;letter-spacing:.04em;margin-bottom:.45rem}
        .callout-copy{font-size:1rem;line-height:1.55;color:#0f172a;margin:0}
        .minor-note{font-size:.86rem;color:#64748b;margin-top:.65rem}
        .section-header{margin:.4rem 0 .8rem}
        .section-header h3{font-size:1.1rem;margin-bottom:.15rem;color:#0f172a}
        .section-header p{color:#64748b;margin:0;font-size:.92rem}
        [data-testid="stMetric"]{position:relative;overflow:hidden;background:rgba(255,255,255,.96);border:1px solid rgba(15,23,42,.075);border-radius:20px;padding:1rem 1.05rem;box-shadow:0 12px 28px rgba(15,23,42,.045);transition:transform 160ms ease,box-shadow 160ms ease}
        [data-testid="stMetric"]:before{content:"";position:absolute;left:0;top:0;width:100%;height:3px;background:linear-gradient(90deg,#2563eb,#60a5fa);opacity:.8}
        [data-testid="stMetric"]:hover{transform:translateY(-1px);box-shadow:0 16px 34px rgba(15,23,42,.065)}
        [data-testid="stMetricLabel"]{color:#64748b;font-weight:600}
        [data-testid="stMetricValue"]{color:#0f172a;font-weight:800}
        [data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:0 10px 24px rgba(15,23,42,.04);background:#fff}
        [data-testid="stExpander"]{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:#fff}
        div[data-baseweb="tab-list"]{gap:.35rem}
        button[data-baseweb="tab"]{border-radius:999px;padding-left:.95rem;padding-right:.95rem;background:rgba(15,23,42,.04)}
        button[data-baseweb="tab"][aria-selected="true"]{background:rgba(37,99,235,.1)}
        .allocation-shell{background:#fff;border:1px solid rgba(15,23,42,.075);border-radius:20px;padding:1rem 1.05rem;box-shadow:0 12px 28px rgba(15,23,42,.04);margin:.9rem 0 1rem}
        .allocation-row{display:flex;justify-content:space-between;gap:1rem;font-size:.86rem;color:#475569;margin-bottom:.55rem}
        .allocation-track{height:.7rem;border-radius:999px;background:#e8edf5;overflow:hidden}
        .allocation-fill{height:100%;border-radius:inherit;background:linear-gradient(90deg,#1d4ed8,#60a5fa)}
        hr{border-color:var(--line)}
        @media(max-width:760px){.block-container{padding:.8rem 1rem 2rem}.hero-card{padding:1.2rem 1.1rem;border-radius:22px}.hero-grid{grid-template-columns:1fr}.hero-monogram{display:none}.hero-title{font-size:1.55rem}.allocation-row{display:block}.allocation-row span{display:block;margin-bottom:.25rem}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(options: list[str]) -> str:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-mark">CI</div>
                <div class="sidebar-brand-title">Capital Intelligence</div>
                <div class="sidebar-brand-copy">One governed portfolio. All-market opportunity analysis. Clear CIO decisions.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        page = st.radio("Navigation", options)
        st.caption("Simple surfaces. Institutional logic. Paper mode.")
    return page


def render_app_header(active_page: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")
    st.markdown(
        f"""
        <div class="hero-card"><div class="hero-grid"><div>
            <div class="hero-eyebrow">AI Chief Investment Officer · Paper mode</div>
            <h1 class="hero-title">{escape(active_page)}</h1>
            <p class="hero-copy">{escape(APP_SUBTITLE)}</p>
            <div class="hero-meta">
                <span class="page-chip primary">COMPOUNDING</span>
                <span class="page-chip">USD base currency</span>
                <span class="page-chip">All governed markets</span>
                <span class="page-chip">Updated {escape(stamp)}</span>
            </div>
        </div><div class="hero-monogram">CI</div></div></div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, description: str) -> None:
    st.markdown(
        f'<div class="section-header"><h3>{escape(title)}</h3><p>{escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def text_card(title: str, body: object) -> None:
    text = "No additional detail is available." if body in (None, "") else str(body)
    st.markdown(
        f'<div class="section-card"><div class="section-title">{escape(title)}</div><p class="section-copy">{escape(text)}</p></div>',
        unsafe_allow_html=True,
    )


def callout_card(title: str, body: object, note: str | None = None) -> None:
    text = "No additional detail is available." if body in (None, "") else str(body)
    note_html = "" if not note else f'<div class="minor-note">{escape(note)}</div>'
    st.markdown(
        f'<div class="callout-card"><div class="callout-title">{escape(title)}</div><p class="callout-copy">{escape(text)}</p>{note_html}</div>',
        unsafe_allow_html=True,
    )


def allocation_bar(*, cash: float, nav: float) -> None:
    invested = max(float(nav) - float(cash), 0.0)
    deployed = 0.0 if nav <= 0 else min(max(invested / float(nav), 0.0), 1.0)
    st.markdown(
        f"""
        <div class="allocation-shell">
            <div class="allocation-row"><span><strong>Capital deployed</strong> · {deployed:.0%}</span><span>{format_currency(invested)} invested · {format_currency(cash)} cash</span></div>
            <div class="allocation-track"><div class="allocation-fill" style="width:{deployed * 100:.2f}%"></div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def bullet_lines(items: Iterable[object]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return "No items are available." if not cleaned else "\n".join(f"- {item}" for item in cleaned)


def display_frame(frame: pd.DataFrame) -> None:
    st.dataframe(frame, use_container_width=True, hide_index=True)
