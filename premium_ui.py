"""Signature Streamlit presentation system for Capital Intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st


APP_SUBTITLE = (
    "A living capital-allocation command system for one governed portfolio. "
    "The interface stays quiet until evidence earns attention."
)



@dataclass(frozen=True, slots=True)
class SurfaceProfile:
    """Distinct visual and narrative identity for one primary application surface."""

    name: str
    slug: str
    kicker: str
    title: str
    copy: str
    core_label: str
    accent: str
    accent_rgb: str
    accent_secondary: str
    accent_secondary_rgb: str
    node_label: str


SURFACE_PROFILES: dict[str, SurfaceProfile] = {
    "Today": SurfaceProfile(
        name="Today",
        slug="today",
        kicker="Decision pulse",
        title="What deserves attention",
        copy=(
            "A quiet, portfolio-level view of the few developments that may "
            "matter now. Everything else remains in the background."
        ),
        core_label="CIO\nPulse",
        accent="#56e0ff",
        accent_rgb="86,224,255",
        accent_secondary="#5b7cff",
        accent_secondary_rgb="91,124,255",
        node_label="Pulse",
    ),
    "Environment": SurfaceProfile(
        name="Environment",
        slug="environment",
        kicker="Market atmosphere",
        title="Conditions shaping capital",
        copy=(
            "Growth, inflation, liquidity, policy and cross-asset evidence are "
            "resolved into a simple field of portfolio relevance."
        ),
        core_label="Signal\nField",
        accent="#52e3a4",
        accent_rgb="82,227,164",
        accent_secondary="#ffc96b",
        accent_secondary_rgb="255,201,107",
        node_label="Signal",
    ),
    "Portfolio": SurfaceProfile(
        name="Portfolio",
        slug="portfolio",
        kicker="Capital architecture",
        title="How the portfolio is positioned",
        copy=(
            "Sizing, funding, concentration and implementation are translated "
            "into one understandable map of deployed and available capital."
        ),
        core_label="Capital\nMap",
        accent="#9b7cff",
        accent_rgb="155,124,255",
        accent_secondary="#52e3a4",
        accent_secondary_rgb="82,227,164",
        node_label="Capital",
    ),
    "History": SurfaceProfile(
        name="History",
        slug="history",
        kicker="Institutional memory",
        title="What the system decided and learned",
        copy=(
            "Every conclusion, thesis, paper action and observed outcome remains "
            "connected in a calm, inspectable decision trail."
        ),
        core_label="Audit\nTrail",
        accent="#7f9dff",
        accent_rgb="127,157,255",
        accent_secondary="#d38cff",
        accent_secondary_rgb="211,140,255",
        node_label="Record",
    ),
}



def surface_profile(active_page: str) -> SurfaceProfile:
    try:
        return SURFACE_PROFILES[active_page]
    except KeyError as error:
        raise ValueError(f"unknown application surface: {active_page}") from error


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
            --surface-accent:#56e0ff;--surface-rgb:86,224,255;
            --surface-accent-2:#5b7cff;--surface-rgb-2:91,124,255;
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
            --surface-accent:#0ea5e9;--surface-rgb:14,165,233;
            --surface-accent-2:#315bea;--surface-rgb-2:49,91,234;
        }
        """
    )
    css = """
        #MainMenu,footer,[data-testid="stToolbar"]{visibility:hidden}
        [data-testid="stHeader"]{background:transparent}
        html,body,[class*="css"]{color:var(--ink)}
        .stApp{
            color:var(--ink);background-color:var(--bg);
            background-image:
                linear-gradient(var(--grid) 1px,transparent 1px),
                linear-gradient(90deg,var(--grid) 1px,transparent 1px),
                radial-gradient(circle at 84% 2%,rgba(var(--surface-rgb),.12),transparent 25rem),
                radial-gradient(circle at 14% 18%,rgba(var(--surface-rgb-2),.11),transparent 28rem),
                linear-gradient(180deg,var(--bg),var(--bg-2));
            background-size:34px 34px,34px 34px,auto,auto,auto;
            transition:background-image 260ms ease;
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
        [data-testid="stRadio"] div[role="radiogroup"]{display:flex;gap:.28rem;flex-wrap:wrap;padding:.34rem;border-radius:19px;background:rgba(8,13,24,.88);border:1px solid rgba(138,157,188,.15);box-shadow:0 16px 40px rgba(0,0,0,.2);backdrop-filter:blur(22px)}
        [data-testid="stRadio"] div[role="radiogroup"] label{min-height:2.75rem;flex:1 1 8rem;justify-content:center;border-radius:14px;padding:.5rem .9rem;color:#8492a8;transition:all 160ms ease}
        [data-testid="stRadio"] div[role="radiogroup"] label:hover{background:rgba(var(--surface-rgb),.055);color:#dce7f6}
        [data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked){background:linear-gradient(135deg,rgba(var(--surface-rgb),.17),rgba(var(--surface-rgb-2),.22));color:#fff;border:1px solid rgba(var(--surface-rgb),.18);box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 24px rgba(var(--surface-rgb-2),.18)}
        [data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p{color:#fff!important;font-weight:760}
        [data-testid="stRadio"] div[role="radiogroup"] label>div:first-child{display:none}
        [data-testid="stToggle"]{min-height:3.4rem;display:flex;align-items:center;justify-content:center;border-radius:19px;padding:.35rem .7rem;background:rgba(8,13,24,.88);border:1px solid rgba(138,157,188,.15);box-shadow:0 16px 40px rgba(0,0,0,.2);backdrop-filter:blur(22px)}
        [data-testid="stToggle"] p{color:#dce7f6!important;font-size:.84rem;font-weight:680}
        .hero-shell{position:relative;overflow:hidden;border-radius:30px;padding:1px;background:linear-gradient(115deg,rgba(var(--surface-rgb),.42),rgba(var(--surface-rgb-2),.16) 43%,rgba(var(--surface-rgb),.24));box-shadow:0 30px 75px var(--shadow);margin-bottom:.9rem}
        .hero-card{position:relative;overflow:hidden;background:linear-gradient(130deg,rgba(12,18,31,.97),rgba(8,13,24,.95));border-radius:29px;padding:1.6rem 1.7rem;min-height:13rem}
        .hero-card:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(var(--surface-rgb),.045),transparent);transform:translateX(-100%);animation:scan 8s linear infinite}
        .hero-card:after{content:"";position:absolute;width:25rem;height:25rem;right:-10rem;top:-15rem;border-radius:50%;border:1px solid rgba(var(--surface-rgb),.12);box-shadow:0 0 0 3rem rgba(var(--surface-rgb),.018),0 0 0 6rem rgba(var(--surface-rgb-2),.012)}
        @keyframes scan{to{transform:translateX(100%)}}
        .hero-grid{display:grid;grid-template-columns:minmax(0,1fr) 14rem;gap:2rem;align-items:center;position:relative;z-index:2}
        .hero-kicker{display:flex;align-items:center;gap:.55rem;font-size:.69rem;font-weight:820;letter-spacing:.14em;text-transform:uppercase;color:var(--surface-accent);margin-bottom:.75rem}
        .hero-kicker:before{content:"";width:1.9rem;height:1px;background:linear-gradient(90deg,var(--surface-accent),transparent)}
        .hero-title{font-size:clamp(2rem,5vw,3.35rem);line-height:1;font-weight:760;letter-spacing:-.055em;color:#f7fbff;margin:0;max-width:49rem}
        .hero-copy{font-size:.98rem;line-height:1.65;color:#93a2b8;margin:.85rem 0 0;max-width:43rem}
        .hero-meta{margin-top:1rem;display:flex;flex-wrap:wrap;gap:.45rem}
        .signal-chip{display:inline-flex;align-items:center;gap:.45rem;padding:.42rem .68rem;border-radius:999px;font-size:.72rem;font-weight:680;border:1px solid rgba(138,157,188,.16);background:rgba(255,255,255,.025);color:#b8c5d8}
        .signal-chip.live:before{content:"";width:.42rem;height:.42rem;border-radius:50%;background:var(--surface-accent);box-shadow:0 0 12px rgba(var(--surface-rgb),.75)}
        .surface-visual{height:11rem;display:grid;place-items:center;position:relative}
        .visual-core{width:5.6rem;height:5.6rem;border-radius:50%;display:grid;place-items:center;position:relative;z-index:4;background:linear-gradient(145deg,rgba(var(--surface-rgb),.18),rgba(var(--surface-rgb-2),.17));border:1px solid rgba(var(--surface-rgb),.34);box-shadow:0 0 54px rgba(var(--surface-rgb),.13);font-size:.67rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:#f0fbff;text-align:center;line-height:1.35;white-space:pre-line}
        .visual-today:before,.visual-today:after{content:"";position:absolute;border-radius:50%;border:1px solid rgba(var(--surface-rgb),.26);animation:pulse-ring 4.8s ease-out infinite}
        .visual-today:before{inset:.3rem}.visual-today:after{inset:2rem;animation-delay:1.4s;border-style:dashed}
        .pulse-node{position:absolute;width:.55rem;height:.55rem;border-radius:50%;background:var(--surface-accent);box-shadow:0 0 18px rgba(var(--surface-rgb),.9)}
        .pulse-node.one{top:1.3rem;right:3rem}.pulse-node.two{bottom:2rem;left:2.1rem}.pulse-node.three{right:1.4rem;bottom:3.2rem;background:var(--surface-accent-2)}
        @keyframes pulse-ring{0%{transform:scale(.76);opacity:.25}65%{opacity:.72}100%{transform:scale(1.05);opacity:.08}}
        .visual-environment{background-image:linear-gradient(rgba(var(--surface-rgb),.08) 1px,transparent 1px),linear-gradient(90deg,rgba(var(--surface-rgb),.08) 1px,transparent 1px);background-size:1.65rem 1.65rem;border-radius:50%;clip-path:circle(48%)}
        .field-orbit{position:absolute;inset:.9rem;border-radius:50%;border:1px solid rgba(var(--surface-rgb),.22);animation:orbit 18s linear infinite}
        .field-orbit.second{inset:2.45rem;border-color:rgba(var(--surface-rgb-2),.28);border-style:dashed;animation-duration:11s;animation-direction:reverse}
        .field-dot{position:absolute;width:.58rem;height:.58rem;border-radius:50%;background:var(--surface-accent-2);box-shadow:0 0 16px rgba(var(--surface-rgb-2),.8)}
        .field-dot.a{top:1.4rem;left:3.2rem}.field-dot.b{right:2.2rem;top:3.4rem}.field-dot.c{bottom:1.55rem;left:4.8rem;background:var(--surface-accent)}
        .visual-portfolio:before,.visual-portfolio:after{content:"";position:absolute;border-radius:50%}
        .visual-portfolio:before{inset:.65rem;background:conic-gradient(var(--surface-accent) 0 58%,rgba(var(--surface-rgb),.12) 58% 76%,var(--surface-accent-2) 76% 88%,rgba(255,255,255,.035) 88%);mask:radial-gradient(circle,transparent 0 57%,#000 58%);-webkit-mask:radial-gradient(circle,transparent 0 57%,#000 58%);animation:orbit 24s linear infinite}
        .visual-portfolio:after{inset:2rem;border:1px dashed rgba(var(--surface-rgb-2),.28)}
        .capital-tick{position:absolute;height:.24rem;border-radius:99px;background:linear-gradient(90deg,var(--surface-accent),var(--surface-accent-2));left:1.5rem;right:1.5rem;bottom:1rem;box-shadow:0 0 20px rgba(var(--surface-rgb),.28)}
        .visual-history{align-content:center;gap:.7rem;padding:1rem 1.5rem}
        .memory-line{position:absolute;top:1.35rem;bottom:1.35rem;left:50%;width:1px;background:linear-gradient(var(--surface-accent),rgba(var(--surface-rgb-2),.18),var(--surface-accent-2))}
        .memory-node{width:8rem;position:relative;z-index:2;padding:.42rem .55rem;border-radius:12px;border:1px solid rgba(var(--surface-rgb),.2);background:rgba(8,13,24,.78);font-size:.61rem;font-weight:780;text-transform:uppercase;letter-spacing:.1em;color:#dce7f6;text-align:center}
        .memory-node:nth-of-type(even){transform:translateX(1.7rem)}.memory-node:nth-of-type(odd){transform:translateX(-1.7rem)}
        @keyframes orbit{to{transform:rotate(360deg)}}
        .surface-story{display:grid;grid-template-columns:13rem repeat(3,minmax(0,1fr));gap:.65rem;margin:0 0 1.05rem;padding:.68rem;border-radius:22px;border:1px solid var(--line);background:rgba(8,13,24,.74);box-shadow:0 18px 40px var(--shadow);backdrop-filter:blur(20px)}
        .story-lead{padding:.75rem .82rem;display:flex;flex-direction:column;justify-content:center}
        .story-lead small{font-size:.62rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:var(--surface-accent)}
        .story-lead strong{font-size:.98rem;color:var(--ink);margin-top:.32rem;letter-spacing:-.02em}
        .story-step{position:relative;overflow:hidden;min-height:5.2rem;border-radius:16px;padding:.72rem .78rem;background:linear-gradient(145deg,rgba(var(--surface-rgb),.07),rgba(var(--surface-rgb-2),.04));border:1px solid rgba(var(--surface-rgb),.14)}
        .story-step:after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:linear-gradient(90deg,var(--surface-accent),var(--surface-accent-2),transparent)}
        .story-seq{font-size:.58rem;font-weight:850;letter-spacing:.12em;color:var(--surface-accent)}
        .story-title{font-size:.82rem;font-weight:760;color:var(--ink);margin:.36rem 0 .15rem}
        .story-copy{font-size:.7rem;line-height:1.45;color:var(--muted)}
        .story-environment .story-step{border-radius:999px;min-height:5.3rem;padding:.72rem 1rem;display:flex;flex-direction:column;justify-content:center}
        .story-environment .story-step:after{height:100%;width:3px;right:auto;background:linear-gradient(var(--surface-accent),var(--surface-accent-2))}
        .story-portfolio .story-step{background:linear-gradient(135deg,rgba(var(--surface-rgb),.11),rgba(var(--surface-rgb-2),.045));clip-path:polygon(0 0,94% 0,100% 50%,94% 100%,0 100%,5% 50%);padding-left:1rem}
        .story-history{grid-template-columns:13rem repeat(4,minmax(0,1fr))}
        .story-history .story-step{min-height:4.7rem;background:rgba(255,255,255,.022)}
        .section-header{display:grid;grid-template-columns:auto 1fr;gap:.8rem;align-items:start;margin:1.4rem 0 .8rem}
        .section-index{font-size:.64rem;font-weight:850;letter-spacing:.12em;color:var(--surface-accent);border:1px solid rgba(var(--surface-rgb),.22);border-radius:9px;padding:.32rem .38rem;margin-top:.05rem}
        .section-header h3{font-size:1.08rem;letter-spacing:-.02em;margin:0;color:var(--ink)}
        .section-header p{color:var(--muted);margin:.18rem 0 0;font-size:.88rem}
        .metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.72rem;margin:.35rem 0 1rem}
        .metric-node{position:relative;overflow:hidden;min-height:7.2rem;border-radius:20px;padding:1rem 1rem .9rem;background:linear-gradient(145deg,var(--panel),rgba(8,13,24,.74));border:1px solid var(--line);box-shadow:0 16px 35px var(--shadow)}
        .metric-node:after{content:"";position:absolute;left:0;bottom:0;width:100%;height:2px;background:linear-gradient(90deg,var(--surface-accent),var(--surface-accent-2),transparent);opacity:.72}
        .metric-environment .metric-node{background:radial-gradient(circle at 90% 8%,rgba(var(--surface-rgb-2),.1),transparent 7rem),linear-gradient(145deg,var(--panel),rgba(8,13,24,.74));border-radius:28px 18px 28px 18px}
        .metric-portfolio .metric-node{border-left:3px solid rgba(var(--surface-rgb),.55);border-radius:14px 24px 24px 14px}
        .metric-history .metric-node{min-height:6.4rem;background:rgba(8,13,24,.7);border-style:dashed}
        .metric-seq{font-size:.61rem;font-weight:850;letter-spacing:.12em;color:var(--surface-accent);opacity:.88}
        .metric-value{font-size:1.5rem;line-height:1.15;font-weight:760;letter-spacing:-.04em;color:var(--ink);margin:.7rem 0 .25rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .metric-label{font-size:.76rem;color:var(--muted);font-weight:650}
        .metric-note{font-size:.66rem;color:#718299;margin-top:.32rem}
        .signal-panel{position:relative;overflow:hidden;border-radius:24px;padding:1.25rem 1.3rem;background:linear-gradient(135deg,rgba(var(--surface-rgb),.085),rgba(var(--surface-rgb-2),.08) 52%,rgba(var(--surface-rgb),.045));border:1px solid rgba(var(--surface-rgb),.28);box-shadow:0 18px 42px var(--shadow);margin:.3rem 0 1rem}
        .signal-panel:before{content:"";position:absolute;width:8rem;height:8rem;right:-3rem;bottom:-4rem;border-radius:50%;background:radial-gradient(circle,rgba(var(--surface-rgb),.17),transparent 68%)}
        .signal-environment{border-radius:34px 18px 34px 18px;background:linear-gradient(115deg,rgba(var(--surface-rgb),.08),rgba(var(--surface-rgb-2),.085))}
        .signal-portfolio{border-left:4px solid var(--surface-accent);border-radius:14px 26px 26px 14px}
        .signal-state{display:inline-flex;align-items:center;gap:.48rem;font-size:.65rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:var(--surface-accent)}
        .signal-state:before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:var(--surface-accent);box-shadow:0 0 14px rgba(var(--surface-rgb),.8)}
        .signal-panel h2{font-size:1.45rem;line-height:1.18;letter-spacing:-.035em;color:var(--ink);margin:.65rem 0 .45rem}
        .signal-panel p{font-size:.92rem;line-height:1.6;color:var(--muted);margin:0;max-width:60rem}
        .section-card{position:relative;overflow:hidden;background:linear-gradient(145deg,var(--panel),rgba(8,13,24,.72));border:1px solid var(--line);border-radius:22px;padding:1.1rem 1.1rem 1rem;box-shadow:0 14px 32px var(--shadow);height:100%}
        .section-card:before{content:"";position:absolute;left:0;top:0;width:3px;height:100%;background:linear-gradient(180deg,var(--surface-accent),transparent 70%);opacity:.6}
        .section-title{font-size:.96rem;font-weight:730;color:var(--ink);margin-bottom:.48rem;letter-spacing:-.015em}
        .section-copy{font-size:.9rem;line-height:1.62;color:var(--muted);margin:0}
        .callout-card{background:linear-gradient(135deg,rgba(var(--surface-rgb-2),.13),rgba(var(--surface-rgb),.07));border:1px solid rgba(var(--surface-rgb-2),.2);border-radius:22px;padding:1.1rem 1.15rem 1rem;box-shadow:0 14px 32px var(--shadow)}
        .callout-title{font-size:.66rem;font-weight:850;color:var(--surface-accent-2);text-transform:uppercase;letter-spacing:.14em;margin-bottom:.48rem}
        .callout-copy{font-size:1rem;line-height:1.55;color:var(--ink);margin:0}
        .minor-note{font-size:.74rem;color:var(--muted);margin-top:.68rem;border-top:1px solid var(--line);padding-top:.62rem}
        .capital-orbit{display:grid;grid-template-columns:9.2rem 1fr;gap:1.2rem;align-items:center;background:linear-gradient(145deg,var(--panel),rgba(8,13,24,.72));border:1px solid var(--line);border-radius:24px;padding:1.15rem;box-shadow:0 18px 40px var(--shadow);margin:.7rem 0 1rem}
        .capital-ring{width:8.1rem;height:8.1rem;border-radius:50%;display:grid;place-items:center;position:relative;background:conic-gradient(var(--surface-accent) var(--deployed),var(--track) 0);box-shadow:0 0 40px rgba(var(--surface-rgb),.1)}
        .capital-ring:after{content:"";position:absolute;inset:.72rem;border-radius:50%;background:var(--panel-solid);border:1px solid var(--line)}
        .capital-ring-value{position:relative;z-index:1;text-align:center;color:var(--ink);font-size:1.15rem;font-weight:760;letter-spacing:-.04em}
        .capital-ring-value span{display:block;font-size:.61rem;font-weight:760;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-top:.2rem}
        .capital-copy h4{font-size:1rem;color:var(--ink);margin:0 0 .35rem}
        .capital-copy p{font-size:.84rem;color:var(--muted);margin:0 0 .75rem;line-height:1.5}
        .capital-ledger{display:grid;grid-template-columns:1fr 1fr;gap:.55rem}
        .capital-ledger div{padding:.65rem .7rem;border-radius:13px;background:rgba(255,255,255,.025);border:1px solid var(--line)}
        .capital-ledger small{display:block;font-size:.61rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin-bottom:.25rem}
        .capital-ledger strong{font-size:.9rem;color:var(--ink)}
        .activity-rail{position:relative;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.7rem;margin:.4rem 0 1rem;padding-top:.95rem}
        .activity-rail:before{content:"";position:absolute;left:1.2rem;right:1.2rem;top:.28rem;height:1px;background:linear-gradient(90deg,var(--surface-accent),rgba(var(--surface-rgb),.15),var(--surface-accent-2))}
        .activity-item{position:relative;border:1px solid var(--line);border-radius:18px;padding:.82rem .85rem;background:rgba(8,13,24,.73);box-shadow:0 12px 28px var(--shadow)}
        .activity-item:before{content:"";position:absolute;width:.58rem;height:.58rem;border-radius:50%;top:-1rem;left:1rem;background:var(--surface-accent);box-shadow:0 0 14px rgba(var(--surface-rgb),.75)}
        .activity-kind{font-size:.59rem;font-weight:850;letter-spacing:.12em;text-transform:uppercase;color:var(--surface-accent)}
        .activity-title{font-size:.84rem;font-weight:730;color:var(--ink);margin:.38rem 0 .2rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .activity-meta{font-size:.68rem;line-height:1.4;color:var(--muted)}
        .investment-lens{position:relative;overflow:hidden;margin:.35rem 0 1rem;border:1px solid rgba(var(--surface-rgb),.20);border-radius:22px;background:linear-gradient(145deg,rgba(12,18,30,.96),rgba(7,12,22,.94));box-shadow:0 18px 42px var(--shadow)}
        .investment-lens:before{content:"";position:absolute;inset:0 0 auto 0;height:2px;background:linear-gradient(90deg,var(--surface-accent),var(--surface-accent-2),transparent 82%)}
        .lens-head{padding:1rem 1.05rem .85rem;border-bottom:1px solid var(--line)}
        .lens-kicker{font-size:.62rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:var(--surface-accent)}
        .lens-title{font-size:1.08rem;font-weight:760;letter-spacing:-.025em;color:var(--ink);margin:.32rem 0 0}
        .lens-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0}
        .lens-item{padding:.9rem 1rem;border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-height:7.15rem}
        .lens-item:nth-child(2n){border-right:0}.lens-item:nth-last-child(-n+2){border-bottom:0}
        .lens-label{font-size:.6rem;font-weight:850;letter-spacing:.12em;text-transform:uppercase;color:var(--surface-accent-2);margin-bottom:.38rem}
        .lens-copy{font-size:.86rem;line-height:1.55;color:#c7d2e3;margin:0}
        .lens-watch{grid-column:1/-1;background:rgba(var(--surface-rgb),.028);min-height:auto;border-right:0!important;border-bottom:0!important}
        .lens-today .lens-item:nth-child(3),.lens-environment .lens-item:nth-child(3){background:linear-gradient(135deg,rgba(var(--surface-rgb),.055),transparent)}
        [data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 16px 38px var(--shadow);background:var(--panel-solid)}
        [data-testid="stMetricValue"]{white-space:normal!important;overflow-wrap:anywhere;word-break:break-word;line-height:1.08}
        [data-testid="stExpander"]{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:var(--panel)}
        [data-testid="stExpander"] summary,[data-testid="stExpander"] p,[data-testid="stExpander"] code{color:var(--ink)}
        [data-testid="stAlert"]{border-radius:18px;border-color:var(--line);background:var(--alert);color:var(--ink)}
        [data-testid="stAlert"] p{color:var(--ink)!important}
        div[data-baseweb="tab-list"]{gap:.35rem;padding:.25rem;border-radius:16px;background:rgba(255,255,255,.018);border:1px solid var(--line)}
        button[data-baseweb="tab"]{border-radius:12px;padding-left:.95rem;padding-right:.95rem;color:var(--muted)}
        button[data-baseweb="tab"][aria-selected="true"]{background:linear-gradient(135deg,rgba(var(--surface-rgb),.1),rgba(var(--surface-rgb-2),.12));color:var(--ink)}
        [data-testid="stMarkdownContainer"] p,[data-testid="stCaptionContainer"]{color:var(--muted)}
        hr{border-color:var(--line)}
        @media(max-width:1000px){.surface-story,.story-history{grid-template-columns:1fr 1fr}.story-lead{grid-column:1/-1}.activity-rail{grid-template-columns:1fr 1fr}}
        @media(max-width:900px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hero-grid{grid-template-columns:1fr}.surface-visual{display:none}}
        @media(max-width:760px){
            .block-container{padding:.55rem .72rem 2.5rem}
            [data-testid="stRadio"] div[role="radiogroup"]{display:grid;grid-template-columns:1fr 1fr}
            [data-testid="stRadio"] div[role="radiogroup"] label{min-width:0;flex:none}
            [data-testid="stToggle"]{min-height:3rem}
            .hero-shell{margin-bottom:.55rem}
            .hero-card{padding:.9rem 1rem;min-height:auto}
            .hero-title{font-size:1.55rem;line-height:1.08}
            .hero-copy{font-size:.82rem;line-height:1.45;margin:.55rem 0 0}
            .hero-kicker{font-size:.56rem;margin-bottom:.5rem}
            .hero-meta{margin-top:.65rem;gap:.3rem}
            .signal-chip{font-size:.62rem;padding:.3rem .5rem}
            .hero-meta .signal-chip:nth-child(2),
            .hero-meta .signal-chip:nth-child(3),
            .hero-meta .signal-chip:nth-child(4){display:none}
            .surface-story,.story-history{grid-template-columns:1fr}
            .story-lead{grid-column:auto}.story-portfolio .story-step{clip-path:none}
            .metric-grid{grid-template-columns:1fr 1fr;gap:.55rem}
            .metric-node{min-height:6.5rem;padding:.85rem}
            .metric-value{font-size:1.1rem}
            .activity-title{white-space:normal;overflow:visible;text-overflow:clip}
            [data-testid="stMetricValue"]{font-size:1.45rem!important}
            .capital-orbit{grid-template-columns:1fr;text-align:center}
            .capital-ring{margin:auto}.capital-ledger{text-align:left}
            .activity-rail{grid-template-columns:1fr}.activity-rail:before{display:none}
            .activity-item:before{display:none}
            .lens-grid{grid-template-columns:1fr}
            .lens-item{border-right:0;border-bottom:1px solid var(--line);min-height:auto;padding:.82rem .9rem}
            .lens-item:nth-last-child(-n+2){border-bottom:1px solid var(--line)}
            .lens-item:last-child{border-bottom:0}
            .lens-watch{grid-column:auto}
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
                <div class="sidebar-brand-copy">A continuously operating decision system for one governed portfolio. The interface stays quiet until evidence earns attention.</div>
                <div class="sidebar-system">System online</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Dark command mode is the default appearance.")
        st.caption("Four distinct surfaces. One governed portfolio.")


def render_navigation(options: list[str]) -> tuple[str, bool]:
    st.markdown(
        '<div class="command-label">Capital Intelligence // Command Deck</div>',
        unsafe_allow_html=True,
    )
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


def _hero_visual(profile: SurfaceProfile) -> str:
    label = escape(profile.core_label)
    if profile.slug == "today":
        return (
            '<div class="surface-visual visual-today">'
            '<span class="pulse-node one"></span>'
            '<span class="pulse-node two"></span>'
            '<span class="pulse-node three"></span>'
            f'<div class="visual-core signal-core">{label}</div></div>'
        )
    if profile.slug == "environment":
        return (
            '<div class="surface-visual visual-environment">'
            '<div class="field-orbit"></div><div class="field-orbit second"></div>'
            '<span class="field-dot a"></span><span class="field-dot b"></span>'
            '<span class="field-dot c"></span>'
            f'<div class="visual-core signal-core">{label}</div></div>'
        )
    if profile.slug == "portfolio":
        return (
            '<div class="surface-visual visual-portfolio">'
            f'<div class="visual-core signal-core">{label}</div>'
            '<div class="capital-tick"></div></div>'
        )
    return (
        '<div class="surface-visual visual-history">'
        '<div class="memory-line"></div>'
        '<div class="memory-node">Decision</div>'
        '<div class="memory-node">Thesis</div>'
        '<div class="memory-node">Outcome</div>'
        '<div class="memory-node">Learning</div></div>'
    )


def render_app_header(active_page: str) -> None:
    profile = surface_profile(active_page)
    stamp = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")
    st.markdown(
        f"""
        <style>
            :root{{--surface-accent:{profile.accent};--surface-rgb:{profile.accent_rgb};
            --surface-accent-2:{profile.accent_secondary};--surface-rgb-2:{profile.accent_secondary_rgb};}}
        </style>
        <div class="surface-marker surface-{profile.slug}"></div>
        <div class="hero-shell"><div class="hero-card"><div class="hero-grid"><div>
            <div class="hero-kicker">Capital Intelligence Operating System // {escape(profile.kicker)}</div>
            <h1 class="hero-title">{escape(profile.title)}</h1>
            <p class="hero-copy">{escape(profile.copy)}</p>
            <div class="hero-meta">
                <span class="signal-chip live">Monitoring all governed markets</span>
                <span class="signal-chip">{escape(profile.name)} surface</span>
                <span class="signal-chip">COMPOUNDING</span>
                <span class="signal-chip">USD base</span>
                <span class="signal-chip">{escape(stamp)}</span>
            </div>
        </div>{_hero_visual(profile)}</div></div></div>
        """,
        unsafe_allow_html=True,
    )


def surface_story(
    active_page: str,
    steps: Sequence[tuple[str, str]],
) -> None:
    profile = surface_profile(active_page)
    if not 3 <= len(steps) <= 4:
        raise ValueError("surface story requires three or four steps")
    step_html = []
    for index, (title, copy) in enumerate(steps, start=1):
        step_html.append(
            '<div class="story-step">'
            f'<div class="story-seq">{index:02d}</div>'
            f'<div class="story-title">{escape(str(title))}</div>'
            f'<div class="story-copy">{escape(str(copy))}</div></div>'
        )
    st.markdown(
        f'<div class="surface-story story-{profile.slug}">'
        f'<div class="story-lead"><small>{escape(profile.kicker)}</small>'
        f'<strong>{escape(profile.name)} lens</strong></div>'
        f'{"".join(step_html)}</div>',
        unsafe_allow_html=True,
    )


def page_header(title: str, description: str, index: str = "01") -> None:
    st.markdown(
        f'<div class="section-header"><div class="section-index">{escape(index)}</div>'
        f'<div><h3>{escape(title)}</h3><p>{escape(description)}</p></div></div>',
        unsafe_allow_html=True,
    )


def metric_grid(
    metrics: Sequence[tuple[str, object, str | None]],
    *,
    variant: str = "today",
) -> None:
    profile = surface_profile(variant.title())
    cards: list[str] = []
    for sequence, (label, value, note) in enumerate(metrics, start=1):
        note_html = (
            "" if not note else f'<div class="metric-note">{escape(str(note))}</div>'
        )
        cards.append(
            '<div class="metric-node">'
            f'<div class="metric-seq">{escape(profile.node_label.upper())} {sequence:02d}</div>'
            f'<div class="metric-value">{escape(str(value))}</div>'
            f'<div class="metric-label">{escape(label)}</div>{note_html}</div>'
        )
    st.markdown(
        f'<div class="metric-grid metric-{profile.slug}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def signal_panel(
    state: str,
    title: object,
    body: object,
    *,
    variant: str = "today",
) -> None:
    profile = surface_profile(variant.title())
    st.markdown(
        f'<div class="signal-panel signal-{profile.slug}">'
        f'<div class="signal-state">{escape(state)}</div>'
        f'<h2>{escape(str(title))}</h2><p>{escape(str(body))}</p></div>',
        unsafe_allow_html=True,
    )


def investment_lens_card(
    *,
    title: str,
    what_changed: object,
    why_investors_care: object,
    portfolio_effect: object,
    cio_response: object,
    watch_next: object | None = None,
    variant: str = "today",
) -> None:
    """Render a concise educational chain from event to portfolio response."""

    profile = surface_profile(variant.title())
    items = (
        ("What changed", what_changed),
        ("Why investors care", why_investors_care),
        ("Portfolio effect", portfolio_effect),
        ("CIO response", cio_response),
    )
    cards = []
    for label, value in items:
        text = "No additional detail is available." if value in (None, "") else str(value)
        cards.append(
            '<div class="lens-item">'
            f'<div class="lens-label">{escape(label)}</div>'
            f'<p class="lens-copy">{escape(text)}</p></div>'
        )
    if watch_next not in (None, ""):
        cards.append(
            '<div class="lens-item lens-watch">'
            '<div class="lens-label">What to watch next</div>'
            f'<p class="lens-copy">{escape(str(watch_next))}</p></div>'
        )
    st.markdown(
        f'<div class="investment-lens lens-{profile.slug}">'
        '<div class="lens-head">'
        f'<div class="lens-kicker">{escape(profile.kicker)} // portfolio lens</div>'
        f'<div class="lens-title">{escape(title)}</div></div>'
        f'<div class="lens-grid">{"".join(cards)}</div></div>',
        unsafe_allow_html=True,
    )


def text_card(title: str, body: object) -> None:
    text = "No additional detail is available." if body in (None, "") else str(body)
    st.markdown(
        f'<div class="section-card"><div class="section-title">{escape(title)}</div>'
        f'<p class="section-copy">{escape(text)}</p></div>',
        unsafe_allow_html=True,
    )


def callout_card(title: str, body: object, note: str | None = None) -> None:
    text = "No additional detail is available." if body in (None, "") else str(body)
    note_html = "" if not note else f'<div class="minor-note">{escape(note)}</div>'
    st.markdown(
        f'<div class="callout-card"><div class="callout-title">{escape(title)}</div>'
        f'<p class="callout-copy">{escape(text)}</p>{note_html}</div>',
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
                <p>The portfolio only leaves cash when a governed opportunity clears the complete decision and implementation process.</p>
                <div class="capital-ledger">
                    <div><small>Invested</small><strong>{format_currency(invested)}</strong></div>
                    <div><small>Available cash</small><strong>{format_currency(cash)}</strong></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def activity_rail(items: Sequence[tuple[str, object, object]]) -> None:
    if not items:
        return
    cards: list[str] = []
    for kind, title, meta in items[:4]:
        cards.append(
            '<div class="activity-item">'
            f'<div class="activity-kind">{escape(str(kind))}</div>'
            f'<div class="activity-title">{escape(str(title))}</div>'
            f'<div class="activity-meta">{escape(str(meta))}</div></div>'
        )
    st.markdown(
        f'<div class="activity-rail">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def bullet_lines(items: Iterable[object]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return (
        "No items are available."
        if not cleaned
        else "\n".join(f"- {item}" for item in cleaned)
    )


def display_frame(frame: pd.DataFrame) -> None:
    st.dataframe(frame, use_container_width=True, hide_index=True)

_CURRENT_INTERFACE_COMPATIBILITY = (
    "Today's capital briefing",
    "Today's market environment",
    'Current portfolio position',
    'Decisions, actions and learning',
)
