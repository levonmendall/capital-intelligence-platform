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


def apply_global_style(*, dark_mode: bool = False) -> None:
    palette = (
        """
        :root{
            --app-bg:#070b14;
            --app-glow:rgba(37,99,235,.18);
            --surface:#111827;
            --surface-soft:#0f172a;
            --surface-raised:#151e2f;
            --surface-gradient:linear-gradient(135deg,rgba(20,29,46,.98),rgba(11,18,32,.98));
            --ink:#f8fafc;
            --ink-soft:#e2e8f0;
            --muted:#94a3b8;
            --blue:#60a5fa;
            --blue-strong:#3b82f6;
            --line:rgba(148,163,184,.16);
            --shadow:rgba(0,0,0,.34);
            --track:#263246;
            --nav:#0b1220;
            --alert-bg:rgba(30,41,59,.78);
        }
        """
        if dark_mode
        else
        """
        :root{
            --app-bg:#f6f8fb;
            --app-glow:rgba(37,99,235,.07);
            --surface:#ffffff;
            --surface-soft:#f8fafc;
            --surface-raised:#ffffff;
            --surface-gradient:linear-gradient(135deg,rgba(255,255,255,.98),rgba(248,251,255,.96));
            --ink:#0f172a;
            --ink-soft:#334155;
            --muted:#64748b;
            --blue:#2563eb;
            --blue-strong:#1d4ed8;
            --line:rgba(15,23,42,.08);
            --shadow:rgba(15,23,42,.07);
            --track:#e8edf5;
            --nav:#ffffff;
            --alert-bg:rgba(255,255,255,.92);
        }
        """
    )
    common = """
        <style>
        #MainMenu,footer,[data-testid="stToolbar"]{visibility:hidden}
        [data-testid="stHeader"]{background:transparent}
        html,body,[class*="css"]{color:var(--ink)}
        .stApp{
            color:var(--ink);
            background:
                radial-gradient(circle at 85% 0%,var(--app-glow),transparent 28rem),
                linear-gradient(180deg,var(--app-bg) 0%,var(--app-bg) 100%);
        }
        .block-container{max-width:1280px;padding-top:1.15rem;padding-bottom:2.5rem}
        [data-testid="stSidebar"]{background:linear-gradient(180deg,#0b1220 0%,#111827 100%);border-right:1px solid rgba(255,255,255,.06)}
        [data-testid="stSidebar"] *{color:#e5e7eb}
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#cbd5e1}
        .sidebar-brand{padding:1.05rem 1rem 1rem;border:1px solid rgba(255,255,255,.09);border-radius:20px;background:linear-gradient(145deg,rgba(255,255,255,.07),rgba(255,255,255,.025));box-shadow:inset 0 1px 0 rgba(255,255,255,.04);margin-bottom:1rem}
        .sidebar-mark{width:2.35rem;height:2.35rem;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,#3b82f6,#1d4ed8);color:white;font-size:.76rem;font-weight:800;letter-spacing:.08em;margin-bottom:.8rem;box-shadow:0 10px 24px rgba(37,99,235,.28)}
        .sidebar-brand-title{font-size:1rem;font-weight:700;color:#fff;margin-bottom:.2rem}
        .sidebar-brand-copy{font-size:.88rem;line-height:1.4;color:#cbd5e1}
        .nav-caption{font-size:.72rem;font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:.15rem 0 .45rem}
        [data-testid="stRadio"]{margin-bottom:.2rem}
        [data-testid="stRadio"] div[role="radiogroup"]{
            display:flex;
            gap:.35rem;
            flex-wrap:wrap;
            padding:.38rem;
            border-radius:18px;
            background:var(--surface);
            border:1px solid var(--line);
            box-shadow:0 10px 28px var(--shadow);
        }
        [data-testid="stRadio"] div[role="radiogroup"] label{
            min-height:2.55rem;
            flex:1 1 8.25rem;
            justify-content:center;
            border-radius:14px;
            padding:.45rem .8rem;
            color:var(--muted);
            transition:background 150ms ease,color 150ms ease,transform 150ms ease;
        }
        [data-testid="stRadio"] div[role="radiogroup"] label:hover{background:var(--surface-soft);color:var(--ink)}
        [data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked){background:linear-gradient(135deg,var(--blue-strong),var(--blue));color:white;box-shadow:0 8px 20px rgba(37,99,235,.24)}
        [data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p{color:white!important;font-weight:700}
        [data-testid="stRadio"] div[role="radiogroup"] label > div:first-child{display:none}
        [data-testid="stToggle"]{
            min-height:3.25rem;
            display:flex;
            align-items:center;
            justify-content:center;
            border-radius:18px;
            padding:.35rem .65rem;
            background:var(--surface);
            border:1px solid var(--line);
            box-shadow:0 10px 28px var(--shadow);
        }
        [data-testid="stToggle"] p{color:var(--ink)!important;font-weight:650;font-size:.88rem}
        .hero-card{position:relative;overflow:hidden;background:var(--surface-gradient);border:1px solid var(--line);border-radius:28px;padding:1.55rem 1.6rem 1.35rem;box-shadow:0 18px 45px var(--shadow);margin-bottom:1.1rem}
        .hero-card:after{content:"";position:absolute;width:18rem;height:18rem;right:-8rem;top:-11rem;border-radius:999px;background:radial-gradient(circle,var(--app-glow),rgba(37,99,235,0));pointer-events:none}
        .hero-grid{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1.5rem;align-items:start;position:relative;z-index:1}
        .hero-monogram{width:4.2rem;height:4.2rem;border-radius:20px;display:grid;place-items:center;background:linear-gradient(145deg,#0f172a,#1e293b);color:#fff;font-size:.9rem;font-weight:800;letter-spacing:.12em;box-shadow:0 16px 32px rgba(0,0,0,.22)}
        .hero-eyebrow{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--blue);margin-bottom:.65rem}
        .hero-title{font-size:1.9rem;line-height:1.1;font-weight:800;color:var(--ink);margin:0}
        .hero-copy{font-size:.98rem;line-height:1.55;color:var(--muted);margin:.6rem 0 0}
        .hero-meta{margin-top:.85rem;display:flex;flex-wrap:wrap;gap:.5rem}
        .page-chip{display:inline-flex;align-items:center;padding:.38rem .72rem;border-radius:999px;font-size:.78rem;font-weight:600;border:1px solid var(--line);background:var(--surface-soft);color:var(--ink-soft)}
        .page-chip.primary{background:rgba(37,99,235,.14);color:var(--blue);border-color:rgba(59,130,246,.22)}
        .section-card{background:var(--surface);border:1px solid var(--line);border-radius:22px;padding:1.1rem 1.1rem .95rem;box-shadow:0 10px 24px var(--shadow);height:100%}
        .section-title{font-size:1rem;font-weight:700;color:var(--ink);margin-bottom:.45rem}
        .section-copy{font-size:.95rem;line-height:1.58;color:var(--muted);margin:0}
        .callout-card{background:linear-gradient(135deg,rgba(37,99,235,.13),rgba(14,165,233,.07));border:1px solid rgba(59,130,246,.18);border-radius:22px;padding:1.1rem 1.1rem 1rem;margin-top:.2rem}
        .callout-title{font-size:.88rem;font-weight:700;color:var(--blue);text-transform:uppercase;letter-spacing:.04em;margin-bottom:.45rem}
        .callout-copy{font-size:1rem;line-height:1.55;color:var(--ink);margin:0}
        .minor-note{font-size:.86rem;color:var(--muted);margin-top:.65rem}
        .section-header{margin:.4rem 0 .8rem}
        .section-header h3{font-size:1.1rem;margin-bottom:.15rem;color:var(--ink)}
        .section-header p{color:var(--muted);margin:0;font-size:.92rem}
        [data-testid="stMetric"]{position:relative;overflow:hidden;background:var(--surface-raised);border:1px solid var(--line);border-radius:20px;padding:1rem 1.05rem;box-shadow:0 12px 28px var(--shadow);transition:transform 160ms ease,box-shadow 160ms ease}
        [data-testid="stMetric"]:before{content:"";position:absolute;left:0;top:0;width:100%;height:3px;background:linear-gradient(90deg,var(--blue-strong),var(--blue));opacity:.85}
        [data-testid="stMetric"]:hover{transform:translateY(-1px)}
        [data-testid="stMetricLabel"]{color:var(--muted);font-weight:600}
        [data-testid="stMetricValue"]{color:var(--ink);font-weight:800}
        [data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:0 10px 24px var(--shadow);background:var(--surface)}
        [data-testid="stExpander"]{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:var(--surface)}
        [data-testid="stExpander"] summary,[data-testid="stExpander"] p,[data-testid="stExpander"] code{color:var(--ink)}
        [data-testid="stAlert"]{border-radius:18px;border-color:var(--line);background:var(--alert-bg);color:var(--ink)}
        [data-testid="stAlert"] p{color:var(--ink)!important}
        div[data-baseweb="tab-list"]{gap:.35rem}
        button[data-baseweb="tab"]{border-radius:999px;padding-left:.95rem;padding-right:.95rem;background:var(--surface-soft);color:var(--muted)}
        button[data-baseweb="tab"][aria-selected="true"]{background:rgba(37,99,235,.14);color:var(--blue)}
        .allocation-shell{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:1rem 1.05rem;box-shadow:0 12px 28px var(--shadow);margin:.9rem 0 1rem}
        .allocation-row{display:flex;justify-content:space-between;gap:1rem;font-size:.86rem;color:var(--muted);margin-bottom:.55rem}
        .allocation-row strong{color:var(--ink)}
        .allocation-track{height:.7rem;border-radius:999px;background:var(--track);overflow:hidden}
        .allocation-fill{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--blue-strong),var(--blue))}
        [data-testid="stMarkdownContainer"] p,[data-testid="stCaptionContainer"]{color:var(--muted)}
        hr{border-color:var(--line)}
        @media(max-width:760px){
            .block-container{padding:.7rem .8rem 2rem}
            .hero-card{padding:1.15rem 1rem;border-radius:22px}
            .hero-grid{grid-template-columns:1fr}
            .hero-monogram{display:none}
            .hero-title{font-size:1.55rem}
            [data-testid="stRadio"] div[role="radiogroup"]{display:grid;grid-template-columns:1fr 1fr}
            [data-testid="stRadio"] div[role="radiogroup"] label{min-width:0;flex:none}
            [data-testid="stToggle"]{min-height:3rem;margin-top:.15rem}
            .allocation-row{display:block}
            .allocation-row span{display:block;margin-bottom:.25rem}
        }
        </style>
    """
    st.markdown(palette + common, unsafe_allow_html=True)


def render_sidebar() -> None:
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
        st.caption(
            "Use the four-screen navigation at the top of the workspace. It remains visible on desktop and mobile."
        )
        st.caption("Simple surfaces. Institutional logic. Paper mode.")


def render_navigation(options: list[str]) -> tuple[str, bool]:
    st.markdown('<div class="nav-caption">Four-screen workspace</div>', unsafe_allow_html=True)
    navigation, appearance = st.columns((5.5, 1.5), gap="small")
    with navigation:
        page = st.radio(
            "Primary screens",
            options,
            horizontal=True,
            label_visibility="collapsed",
            key="primary_surface",
        )
    with appearance:
        dark_mode = st.toggle("Dark mode", key="dark_mode")
    return page, bool(dark_mode)


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
