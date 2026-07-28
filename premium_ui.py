"""Signature Streamlit presentation system for Capital Intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st


APP_SUBTITLE = (
    "A living capital-allocation command system for one governed portfolio."
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


def apply_global_style(*, dark_mode: bool = True) -> None:
    palette = (
        """
        :root{
            --bg:#05070d;--bg-2:#080d18;--panel:rgba(13,19,32,.88);
            --panel-solid:#0d1320;--panel-2:#111a2b;--ink:#f8fafc;
            --ink-soft:#dce7f6;--muted:#8492a8;--line:rgba(138,157,188,.15);
            --line-hot:rgba(86,224,255,.28);--cyan:#56e0ff;--blue:#5b7cff;
            --violet:#9b7cff;--green:#52e3a4;--amber:#ffc96b;
            --shadow:rgba(0,0,0,.42);--grid:rgba(105,137,187,.055);
            --alert:rgba(17,26,43,.92);--track:#1b2638;
        }
        """
        if dark_mode
        else
        """
        :root{
            --bg:#eef3f9;--bg-2:#f7faff;--panel:rgba(255,255,255,.9);
            --panel-solid:#ffffff;--panel-2:#f5f8fc;--ink:#0b1220;
            --ink-soft:#24324a;--muted:#64748b;--line:rgba(15,23,42,.09);
            --line-hot:rgba(37,99,235,.2);--cyan:#0ea5e9;--blue:#315bea;
            --violet:#7957db;--green:#0f9f6e;--amber:#d98a16;
            --shadow:rgba(15,23,42,.1);--grid:rgba(37,99,235,.045);
            --alert:rgba(255,255,255,.95);--track:#dfe7f2;
        }
        """
    )
    css = """
        #MainMenu,footer,[data-testid="stToolbar"]{visibility:hidden}
        [data-testid="stHeader"]{background:transparent}
        html,body,[class*="css"]{color:var(--ink)}
        .stApp{
            color:var(--ink);
            background-color:var(--bg);
            background-image:
                linear-gradient(var(--grid) 1px,transparent 1px),
                linear-gradient(90deg,var(--grid) 1px,transparent 1px),
                radial-gradient(circle at 84% 2%,rgba(86,224,255,.12),transparent 25rem),
                radial-gradient(circle at 14% 18%,rgba(91,124,255,.12),transparent 28rem),
                linear-gradient(180deg,var(--bg),var(--bg-2));
            background-size:34px 34px,34px 34px,auto,auto,auto;
        }
        .block-container{max-width:1320px;padding-top:.75rem;padding-bottom:3rem}
        [data-testid="stSidebar"]{background:#070b13;border-right:1px solid rgba(255,255,255,.06)}
        [data-testid="stSidebar"] *{color:#e5edf8}
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#8fa0b8}
        .sidebar-brand{padding:1.15rem 1rem;border:1px solid rgba(255,255,255,.08);border-radius:22px;background:linear-gradient(145deg,rgba(255,255,255,.055),rgba(255,255,255,.018));margin-bottom:1rem;position:relative;overflow:hidden}
        .sidebar-brand:after{content:"";position:absolute;width:7rem;height:7rem;border:1px solid rgba(86,224,255,.16);border-radius:50%;right:-3.7rem;top:-3.7rem;box-shadow:0 0 40px rgba(86,224,255,.08)}
        .sidebar-mark{width:2.65rem;height:2.65rem;border-radius:15px;display:grid;place-items:center;background:linear-gradient(135deg,#56e0ff,#5b7cff 58%,#9b7cff);color:#06101a;font-size:.72rem;font-weight:900;letter-spacing:.12em;margin-bottom:.85rem;box-shadow:0 12px 34px rgba(86,224,255,.2)}
        .sidebar-brand-title{font-size:1rem;font-weight:760;color:#fff;margin-bottom:.25rem;letter-spacing:-.015em}
        .sidebar-brand-copy{font-size:.83rem;line-height:1.5;color:#8fa0b8;max-width:13rem}
        .sidebar-system{display:flex;align-items:center;gap:.5rem;margin-top:1rem;font-size:.72rem;color:#718299;text-transform:uppercase;letter-spacing:.08em}
        .sidebar-system:before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:#52e3a4;box-shadow:0 0 16px rgba(82,227,164,.7)}
        .command-label{font-size:.68rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:.3rem 0 .5rem}
        .command-dock{position:relative;z-index:4;margin-bottom:.75rem}
        [data-testid="stRadio"] div[role="radiogroup"]{display:flex;gap:.28rem;flex-wrap:wrap;padding:.34rem;border-radius:19px;background:rgba(8,13,24,.88);border:1px solid rgba(138,157,188,.15);box-shadow:0 16px 40px rgba(0,0,0,.2);backdrop-filter:blur(22px)}
        [data-testid="stRadio"] div[role="radiogroup"] label{min-height:2.75rem;flex:1 1 8rem;justify-content:center;border-radius:14px;padding:.5rem .9rem;color:#8492a8;transition:all 160ms ease}
        [data-testid="stRadio"] div[role="radiogroup"] label:hover{background:rgba(86,224,255,.055);color:#dce7f6}
        [data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked){background:linear-gradient(135deg,rgba(86,224,255,.17),rgba(91,124,255,.22));color:#fff;border:1px solid rgba(86,224,255,.18);box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 24px rgba(27,74,140,.18)}
        [data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p{color:#fff!important;font-weight:760}
        [data-testid="stRadio"] div[role="radiogroup"] label>div:first-child{display:none}
        [data-testid="stToggle"]{min-height:3.4rem;display:flex;align-items:center;justify-content:center;border-radius:19px;padding:.35rem .7rem;background:rgba(8,13,24,.88);border:1px solid rgba(138,157,188,.15);box-shadow:0 16px 40px rgba(0,0,0,.2);backdrop-filter:blur(22px)}
        [data-testid="stToggle"] p{color:#dce7f6!important;font-size:.84rem;font-weight:680}
        .hero-shell{position:relative;overflow:hidden;border-radius:30px;padding:1px;background:linear-gradient(115deg,rgba(86,224,255,.34),rgba(91,124,255,.14) 38%,rgba(155,124,255,.28));box-shadow:0 30px 75px var(--shadow);margin-bottom:1.2rem}
        .hero-card{position:relative;overflow:hidden;background:linear-gradient(130deg,rgba(12,18,31,.97),rgba(8,13,24,.95));border-radius:29px;padding:1.55rem 1.65rem;min-height:13rem}
        .hero-card:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(86,224,255,.04),transparent);transform:translateX(-100%);animation:scan 8s linear infinite}
        .hero-card:after{content:"";position:absolute;width:25rem;height:25rem;right:-10rem;top:-15rem;border-radius:50%;border:1px solid rgba(86,224,255,.12);box-shadow:0 0 0 3rem rgba(86,224,255,.018),0 0 0 6rem rgba(91,124,255,.012)}
        @keyframes scan{to{transform:translateX(100%)}}
        .hero-grid{display:grid;grid-template-columns:minmax(0,1fr) 13rem;gap:2rem;align-items:center;position:relative;z-index:2}
        .hero-kicker{display:flex;align-items:center;gap:.55rem;font-size:.69rem;font-weight:820;letter-spacing:.14em;text-transform:uppercase;color:var(--cyan);margin-bottom:.75rem}
        .hero-kicker:before{content:"";width:1.9rem;height:1px;background:linear-gradient(90deg,var(--cyan),transparent)}
        .hero-title{font-size:clamp(2rem,5vw,3.4rem);line-height:.98;font-weight:760;letter-spacing:-.055em;color:#f7fbff;margin:0;max-width:47rem}
        .hero-copy{font-size:.98rem;line-height:1.65;color:#93a2b8;margin:.85rem 0 0;max-width:43rem}
        .hero-meta{margin-top:1rem;display:flex;flex-wrap:wrap;gap:.45rem}
        .signal-chip{display:inline-flex;align-items:center;gap:.45rem;padding:.42rem .68rem;border-radius:999px;font-size:.72rem;font-weight:680;border:1px solid rgba(138,157,188,.16);background:rgba(255,255,255,.025);color:#b8c5d8}
        .signal-chip.live:before{content:"";width:.42rem;height:.42rem;border-radius:50%;background:var(--green);box-shadow:0 0 12px rgba(82,227,164,.75)}
        .signal-core{width:10.5rem;height:10.5rem;border-radius:50%;display:grid;place-items:center;position:relative;margin:auto;background:radial-gradient(circle,rgba(86,224,255,.11),rgba(91,124,255,.045) 45%,transparent 70%)}
        .signal-core:before,.signal-core:after{content:"";position:absolute;border-radius:50%;border:1px solid rgba(86,224,255,.22)}
        .signal-core:before{inset:.35rem;animation:orbit 18s linear infinite}
        .signal-core:after{inset:1.65rem;border-style:dashed;border-color:rgba(155,124,255,.3);animation:orbit 12s linear reverse infinite}
        .signal-core-inner{width:5.5rem;height:5.5rem;border-radius:50%;display:grid;place-items:center;background:linear-gradient(145deg,rgba(86,224,255,.16),rgba(91,124,255,.17));border:1px solid rgba(86,224,255,.3);box-shadow:0 0 50px rgba(86,224,255,.11);font-size:.67rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:#dffaff;text-align:center;line-height:1.35}
        @keyframes orbit{to{transform:rotate(360deg)}}
        .section-header{display:grid;grid-template-columns:auto 1fr;gap:.8rem;align-items:start;margin:1.4rem 0 .8rem}
        .section-index{font-size:.64rem;font-weight:850;letter-spacing:.12em;color:var(--cyan);border:1px solid rgba(86,224,255,.2);border-radius:9px;padding:.32rem .38rem;margin-top:.05rem}
        .section-header h3{font-size:1.08rem;letter-spacing:-.02em;margin:0;color:var(--ink)}
        .section-header p{color:var(--muted);margin:.18rem 0 0;font-size:.88rem}
        .metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.72rem;margin:.35rem 0 1rem}
        .metric-node{position:relative;overflow:hidden;min-height:7.2rem;border-radius:20px;padding:1rem 1rem .9rem;background:linear-gradient(145deg,var(--panel),rgba(8,13,24,.74));border:1px solid var(--line);box-shadow:0 16px 35px var(--shadow)}
        .metric-node:after{content:"";position:absolute;left:0;bottom:0;width:100%;height:2px;background:linear-gradient(90deg,var(--cyan),var(--blue),transparent);opacity:.72}
        .metric-seq{font-size:.61rem;font-weight:850;letter-spacing:.12em;color:var(--cyan);opacity:.86}
        .metric-value{font-size:1.5rem;line-height:1.15;font-weight:760;letter-spacing:-.04em;color:var(--ink);margin:.7rem 0 .25rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .metric-label{font-size:.76rem;color:var(--muted);font-weight:650}
        .metric-note{font-size:.66rem;color:#718299;margin-top:.32rem}
        .signal-panel{position:relative;overflow:hidden;border-radius:24px;padding:1.25rem 1.3rem;background:linear-gradient(135deg,rgba(86,224,255,.08),rgba(91,124,255,.08) 52%,rgba(155,124,255,.065));border:1px solid var(--line-hot);box-shadow:0 18px 42px var(--shadow);margin:.3rem 0 1rem}
        .signal-panel:before{content:"";position:absolute;width:8rem;height:8rem;right:-3rem;bottom:-4rem;border-radius:50%;background:radial-gradient(circle,rgba(86,224,255,.15),transparent 68%)}
        .signal-state{display:inline-flex;align-items:center;gap:.48rem;font-size:.65rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:var(--cyan)}
        .signal-state:before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:var(--cyan);box-shadow:0 0 14px rgba(86,224,255,.8)}
        .signal-panel h2{font-size:1.45rem;line-height:1.18;letter-spacing:-.035em;color:var(--ink);margin:.65rem 0 .45rem}
        .signal-panel p{font-size:.92rem;line-height:1.6;color:var(--muted);margin:0;max-width:60rem}
        .section-card{position:relative;overflow:hidden;background:linear-gradient(145deg,var(--panel),rgba(8,13,24,.72));border:1px solid var(--line);border-radius:22px;padding:1.1rem 1.1rem 1rem;box-shadow:0 14px 32px var(--shadow);height:100%}
        .section-card:before{content:"";position:absolute;left:0;top:0;width:3px;height:100%;background:linear-gradient(180deg,var(--cyan),transparent 70%);opacity:.6}
        .section-title{font-size:.96rem;font-weight:730;color:var(--ink);margin-bottom:.48rem;letter-spacing:-.015em}
        .section-copy{font-size:.9rem;line-height:1.62;color:var(--muted);margin:0}
        .callout-card{background:linear-gradient(135deg,rgba(91,124,255,.13),rgba(155,124,255,.07));border:1px solid rgba(155,124,255,.2);border-radius:22px;padding:1.1rem 1.15rem 1rem;box-shadow:0 14px 32px var(--shadow)}
        .callout-title{font-size:.66rem;font-weight:850;color:#b9a7ff;text-transform:uppercase;letter-spacing:.14em;margin-bottom:.48rem}
        .callout-copy{font-size:1rem;line-height:1.55;color:var(--ink);margin:0}
        .minor-note{font-size:.74rem;color:var(--muted);margin-top:.68rem;border-top:1px solid var(--line);padding-top:.62rem}
        .capital-orbit{display:grid;grid-template-columns:9.2rem 1fr;gap:1.2rem;align-items:center;background:linear-gradient(145deg,var(--panel),rgba(8,13,24,.72));border:1px solid var(--line);border-radius:24px;padding:1.15rem;box-shadow:0 18px 40px var(--shadow);margin:.7rem 0 1rem}
        .capital-ring{width:8.1rem;height:8.1rem;border-radius:50%;display:grid;place-items:center;position:relative;background:conic-gradient(var(--cyan) var(--deployed),var(--track) 0);box-shadow:0 0 40px rgba(86,224,255,.08)}
        .capital-ring:after{content:"";position:absolute;inset:.72rem;border-radius:50%;background:var(--panel-solid);border:1px solid var(--line)}
        .capital-ring-value{position:relative;z-index:1;text-align:center;color:var(--ink);font-size:1.15rem;font-weight:760;letter-spacing:-.04em}
        .capital-ring-value span{display:block;font-size:.61rem;font-weight:760;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-top:.2rem}
        .capital-copy h4{font-size:1rem;color:var(--ink);margin:0 0 .35rem}
        .capital-copy p{font-size:.84rem;color:var(--muted);margin:0 0 .75rem;line-height:1.5}
        .capital-ledger{display:grid;grid-template-columns:1fr 1fr;gap:.55rem}
        .capital-ledger div{padding:.65rem .7rem;border-radius:13px;background:rgba(255,255,255,.025);border:1px solid var(--line)}
        .capital-ledger small{display:block;font-size:.61rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin-bottom:.25rem}
        .capital-ledger strong{font-size:.9rem;color:var(--ink)}
        [data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 16px 38px var(--shadow);background:var(--panel-solid)}
        [data-testid="stExpander"]{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:var(--panel)}
        [data-testid="stExpander"] summary,[data-testid="stExpander"] p,[data-testid="stExpander"] code{color:var(--ink)}
        [data-testid="stAlert"]{border-radius:18px;border-color:var(--line);background:var(--alert);color:var(--ink)}
        [data-testid="stAlert"] p{color:var(--ink)!important}
        div[data-baseweb="tab-list"]{gap:.35rem;padding:.25rem;border-radius:16px;background:rgba(255,255,255,.018);border:1px solid var(--line)}
        button[data-baseweb="tab"]{border-radius:12px;padding-left:.95rem;padding-right:.95rem;color:var(--muted)}
        button[data-baseweb="tab"][aria-selected="true"]{background:linear-gradient(135deg,rgba(86,224,255,.1),rgba(91,124,255,.12));color:var(--ink)}
        [data-testid="stMarkdownContainer"] p,[data-testid="stCaptionContainer"]{color:var(--muted)}
        hr{border-color:var(--line)}
        @media(max-width:900px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hero-grid{grid-template-columns:1fr}.signal-core{display:none}}
        @media(max-width:760px){
            .block-container{padding:.55rem .72rem 2.5rem}
            [data-testid="stRadio"] div[role="radiogroup"]{display:grid;grid-template-columns:1fr 1fr}
            [data-testid="stRadio"] div[role="radiogroup"] label{min-width:0;flex:none}
            [data-testid="stToggle"]{min-height:3rem}
            .hero-card{padding:1.2rem 1rem;min-height:auto}
            .hero-title{font-size:2rem}
            .metric-grid{grid-template-columns:1fr 1fr;gap:.55rem}
            .metric-node{min-height:6.5rem;padding:.85rem}
            .metric-value{font-size:1.25rem}
            .capital-orbit{grid-template-columns:1fr;text-align:center}
            .capital-ring{margin:auto}
            .capital-ledger{text-align:left}
        }
    """
    st.markdown(f"<style>{palette}{css}</style>", unsafe_allow_html=True)


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-mark">CI</div>
                <div class="sidebar-brand-title">Capital Intelligence</div>
                <div class="sidebar-brand-copy">A continuously operating decision system for one governed portfolio.</div>
                <div class="sidebar-system">System online</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Dark command mode is the default appearance.")
        st.caption("Four surfaces. One portfolio. No noise.")


def render_navigation(options: list[str]) -> tuple[str, bool]:
    st.markdown('<div class="command-label">Capital Intelligence // Command Deck</div>', unsafe_allow_html=True)
    navigation, appearance = st.columns((5.8, 1.2), gap="small")
    with navigation:
        page = st.radio(
            "Primary screens",
            options,
            horizontal=True,
            label_visibility="collapsed",
            key="primary_surface",
        )
    with appearance:
        dark_mode = st.toggle("Dark", key="dark_mode")
    return page, bool(dark_mode)


def render_app_header(active_page: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")
    st.markdown(
        f"""
        <div class="hero-shell"><div class="hero-card"><div class="hero-grid"><div>
            <div class="hero-kicker">Capital Intelligence Operating System</div>
            <h1 class="hero-title">{escape(active_page)}<br/>Command Surface</h1>
            <p class="hero-copy">{escape(APP_SUBTITLE)} The interface stays quiet until evidence earns attention.</p>
            <div class="hero-meta">
                <span class="signal-chip live">Monitoring all governed markets</span>
                <span class="signal-chip">COMPOUNDING</span>
                <span class="signal-chip">USD base</span>
                <span class="signal-chip">{escape(stamp)}</span>
            </div>
        </div><div class="signal-core"><div class="signal-core-inner">CIO<br/>Core</div></div></div></div></div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, description: str, index: str = "01") -> None:
    st.markdown(
        f'<div class="section-header"><div class="section-index">{escape(index)}</div><div><h3>{escape(title)}</h3><p>{escape(description)}</p></div></div>',
        unsafe_allow_html=True,
    )


def metric_grid(metrics: Sequence[tuple[str, object, str | None]]) -> None:
    cards: list[str] = []
    for sequence, (label, value, note) in enumerate(metrics, start=1):
        note_html = "" if not note else f'<div class="metric-note">{escape(str(note))}</div>'
        cards.append(
            f'<div class="metric-node"><div class="metric-seq">NODE {sequence:02d}</div><div class="metric-value">{escape(str(value))}</div><div class="metric-label">{escape(label)}</div>{note_html}</div>'
        )
    st.markdown(f'<div class="metric-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def signal_panel(state: str, title: object, body: object) -> None:
    st.markdown(
        f'<div class="signal-panel"><div class="signal-state">{escape(state)}</div><h2>{escape(str(title))}</h2><p>{escape(str(body))}</p></div>',
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
        <div class="capital-orbit">
            <div class="capital-ring" style="--deployed:{deployed * 100:.2f}%"><div class="capital-ring-value">{deployed:.0%}<span>deployed</span></div></div>
            <div class="capital-copy">
                <h4>Capital Deployment Orbit</h4>
                <p>The portfolio only leaves cash when a governed opportunity clears the full decision and implementation process.</p>
                <div class="capital-ledger">
                    <div><small>Invested</small><strong>{format_currency(invested)}</strong></div>
                    <div><small>Available cash</small><strong>{format_currency(cash)}</strong></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def bullet_lines(items: Iterable[object]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return "No items are available." if not cleaned else "\n".join(f"- {item}" for item in cleaned)


def display_frame(frame: pd.DataFrame) -> None:
    st.dataframe(frame, use_container_width=True, hide_index=True)
