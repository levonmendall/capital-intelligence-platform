"""Crypto-style Portfolio Command Center for the Capital Intelligence operating phase.

The production presentation deliberately mirrors the Crypto Opportunity Engine command
center: one canonical $250,000 paper portfolio, a dominant NAV/status view, compact
capital/performance metrics, visible positions and implementation history, explicit
operating pipeline health, and a short queue of what needs attention next.

This module is presentation-only. It cannot authorize a CIO decision, alter construction,
lower any evidence/risk/liquidity/cost threshold, or create live-money authority.
"""

from __future__ import annotations

import html
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st

from operating_status import load_cio_operating_status
from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from premium_ui import apply_global_style, format_currency, format_percent


_GENESIS_CAPITAL = 250_000.0


def portfolio_only_enabled() -> bool:
    raw = os.getenv("CAPITAL_INTELLIGENCE_PORTFOLIO_ONLY_UI")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("RENDER", "").strip().lower() == "true"


def _drawdown(snapshots: list[dict[str, Any]]) -> float:
    navs = [
        float(item.get("nav", 0.0) or 0.0)
        for item in sorted(snapshots, key=lambda item: str(item.get("created_at", "")))
        if float(item.get("nav", 0.0) or 0.0) > 0.0
    ]
    if not navs:
        return 0.0
    peak = navs[0]
    worst = 0.0
    for nav in navs:
        peak = max(peak, nav)
        if peak > 0.0:
            worst = min(worst, nav / peak - 1.0)
    return worst


def _deployed(cash: float, nav: float) -> float:
    return 0.0 if nav <= 0.0 else max(0.0, min(1.0, (nav - cash) / nav))


def _positions_frame(holdings: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(holdings)
    if frame.empty:
        return frame
    columns = [
        item
        for item in (
            "symbol",
            "asset_class",
            "quantity",
            "current_price",
            "market_value",
            "unrealized_gain",
            "unrealized_return",
        )
        if item in frame.columns
    ]
    return frame[columns] if columns else frame


def _trades_frame(trades: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(trades[:25])
    if frame.empty:
        return frame
    columns = [
        item
        for item in (
            "created_at",
            "side",
            "symbol",
            "asset_class",
            "quantity",
            "price",
            "gross_amount_base",
            "realized_pnl_base",
            "cost_amount_base",
        )
        if item in frame.columns
    ]
    return frame[columns] if columns else frame


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_number(mapping: Mapping[str, Any], names: Sequence[str], default: float = 0.0) -> float:
    for name in names:
        if name in mapping and mapping.get(name) is not None:
            return _number(mapping.get(name), default)
    return default


def _format_money(value: object) -> str:
    return format_currency(_number(value))


def _format_pct(value: object) -> str:
    return format_percent(_number(value))


def _pnl_class(value: object) -> str:
    number = _number(value)
    return "good" if number > 0 else "bad" if number < 0 else "muted"


def _when(value: object) -> str:
    if value in (None, ""):
        return "—"
    text = str(value).strip()
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%b %d, %-I:%M %p")


def _latest_snapshot(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        return {}
    return max(snapshots, key=lambda item: str(item.get("created_at", "")))


def _realized_pnl(trades: list[dict[str, Any]], latest_snapshot: Mapping[str, Any]) -> float:
    snapshot_value = _first_number(
        latest_snapshot,
        ("realized_pnl", "realized_pnl_base", "realized_gain"),
        default=float("nan"),
    )
    if snapshot_value == snapshot_value:
        return snapshot_value
    return sum(_first_number(item, ("realized_pnl_base", "realized_pnl", "realized_gain")) for item in trades)


def _unrealized_pnl(holdings: list[dict[str, Any]], latest_snapshot: Mapping[str, Any]) -> float:
    snapshot_value = _first_number(
        latest_snapshot,
        ("unrealized_pnl", "unrealized_pnl_base", "unrealized_gain"),
        default=float("nan"),
    )
    if snapshot_value == snapshot_value:
        return snapshot_value
    return sum(_first_number(item, ("unrealized_gain", "unrealized_pnl", "unrealized_pnl_base")) for item in holdings)


def _equity_svg(snapshots: list[dict[str, Any]]) -> str:
    rows: list[tuple[str, float]] = []
    for item in sorted(snapshots, key=lambda row: str(row.get("created_at", ""))):
        nav = _number(item.get("nav"), 0.0)
        if nav > 0.0:
            rows.append((str(item.get("created_at", "")), nav))
    if len(rows) < 2:
        return '<div class="chart-empty">Waiting for more NAV snapshots</div>'

    width, height, pad = 720.0, 260.0, 24.0
    values = [value for _stamp, value in rows]
    low = min(min(values), _GENESIS_CAPITAL)
    high = max(max(values), _GENESIS_CAPITAL)
    span = max(1.0, high - low)
    points: list[str] = []
    for index, (_stamp, value) in enumerate(rows):
        x = pad + (width - 2 * pad) * index / max(1, len(rows) - 1)
        y = height - pad - (height - 2 * pad) * (value - low) / span
        points.append(f"{x:.2f},{y:.2f}")
    genesis_y = height - pad - (height - 2 * pad) * (_GENESIS_CAPITAL - low) / span
    horizontal = "".join(
        f'<line x1="{pad}" y1="{pad + (height - 2 * pad) * i / 3:.2f}" x2="{width-pad}" y2="{pad + (height - 2 * pad) * i / 3:.2f}" class="grid-line" />'
        for i in range(4)
    )
    return (
        f'<svg viewBox="0 0 {int(width)} {int(height)}" class="equity-svg" preserveAspectRatio="none" aria-label="Portfolio NAV history">'
        f"{horizontal}"
        f'<line x1="{pad}" y1="{genesis_y:.2f}" x2="{width-pad}" y2="{genesis_y:.2f}" class="genesis-line" />'
        f'<polyline points="{" ".join(points)}" class="equity-line" />'
        "</svg>"
    )


def _attribution_rows(
    holdings: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> list[tuple[str, float]]:
    grouped: defaultdict[str, float] = defaultdict(float)
    for item in holdings:
        key = str(item.get("asset_class") or item.get("symbol") or "Open positions")
        grouped[f"Asset · {key}"] += _first_number(
            item, ("unrealized_gain", "unrealized_pnl", "unrealized_pnl_base")
        )
    for item in trades:
        key = str(item.get("asset_class") or item.get("symbol") or "Implementation")
        grouped[f"Realized · {key}"] += _first_number(
            item, ("realized_pnl_base", "realized_pnl", "realized_gain")
        )
    return sorted(grouped.items(), key=lambda item: abs(item[1]), reverse=True)[:8]


def _attribution_html(rows: list[tuple[str, float]]) -> str:
    nonzero = [(name, value) for name, value in rows if abs(value) > 1e-12]
    if not nonzero:
        return '<div class="muted">No realized or open-position attribution yet.</div>'
    maximum = max(max(abs(value) for _name, value in nonzero), 1.0)
    result: list[str] = []
    for name, value in nonzero:
        width = max(2.0, abs(value) / maximum * 100.0)
        negative = " neg" if value < 0 else ""
        result.append(
            '<div class="bar-row">'
            f'<div class="bar-name" title="{_esc(name)}">{_esc(name)}</div>'
            f'<div class="bar-track"><div class="bar-fill{negative}" style="width:{width:.1f}%"></div></div>'
            f'<div class="bar-val {_pnl_class(value)}">{_format_money(value)}</div>'
            "</div>"
        )
    return "".join(result)


def _positions_html(holdings: list[dict[str, Any]]) -> tuple[str, str]:
    if not holdings:
        empty = '<div class="muted">The portfolio currently holds cash only.</div>'
        return '<tr><td colspan="8" class="muted">The portfolio currently holds cash only.</td></tr>', empty

    table_rows: list[str] = []
    mobile_rows: list[str] = []
    for item in holdings:
        symbol = item.get("symbol") or "—"
        asset_class = item.get("asset_class") or "—"
        quantity = item.get("quantity")
        price = item.get("current_price")
        market_value = item.get("market_value")
        cost_basis = item.get("cost_basis")
        unrealized = _first_number(item, ("unrealized_gain", "unrealized_pnl", "unrealized_pnl_base"))
        unrealized_return = _first_number(item, ("unrealized_return", "unrealized_return_fraction"))
        table_rows.append(
            "<tr>"
            f"<td><strong>{_esc(symbol)}</strong><br><span class=\"muted\">{_esc(asset_class)}</span></td>"
            f"<td class=\"num\">{_esc(quantity if quantity is not None else '—')}</td>"
            f"<td class=\"num\">{_format_money(cost_basis)}</td>"
            f"<td class=\"num\">{_format_money(price)}</td>"
            f"<td class=\"num\">{_format_money(market_value)}</td>"
            f"<td class=\"num {_pnl_class(unrealized)}\">{_format_money(unrealized)}</td>"
            f"<td class=\"num {_pnl_class(unrealized_return)}\">{_format_pct(unrealized_return)}</td>"
            f"<td>{_esc(_when(item.get('updated_at')))}</td>"
            "</tr>"
        )
        mobile_rows.append(
            '<div class="item"><div class="item-top"><div>'
            f'<div class="item-title">{_esc(symbol)} · {_esc(asset_class)}</div>'
            f'<div class="item-sub">{_format_money(market_value)} market value · {_format_money(price)} mark</div>'
            f'</div><div class="item-pnl {_pnl_class(unrealized)}">{_format_money(unrealized)}</div>'
            '</div></div>'
        )
    return "".join(table_rows), "".join(mobile_rows)


def _trade_item(item: Mapping[str, Any]) -> str:
    realized = _first_number(item, ("realized_pnl_base", "realized_pnl", "realized_gain"))
    side = str(item.get("side") or "trade").upper()
    symbol = str(item.get("symbol") or "—")
    asset_class = str(item.get("asset_class") or "—")
    detail = f"{side} · {asset_class} · {_when(item.get('created_at'))}"
    return (
        '<div class="item"><div class="item-top"><div>'
        f'<div class="item-title">{_esc(symbol)}</div><div class="item-sub">{_esc(detail)}</div>'
        f'</div><div class="item-pnl {_pnl_class(realized)}">{_format_money(realized)}</div>'
        '</div></div>'
    )


def _construction_rejections(construction: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(construction, Mapping):
        return []
    rows: list[str] = []
    raw_blocks = construction.get("blocks", ())
    if isinstance(raw_blocks, (list, tuple)):
        rows.extend(str(item).strip() for item in raw_blocks if str(item).strip())
    for field_name in ("blockers", "rejections", "rejection_reasons"):
        value = construction.get(field_name)
        if isinstance(value, (list, tuple)):
            rows.extend(str(item).strip() for item in value if str(item).strip())
    return list(dict.fromkeys(rows))[:12]


def _status_class(label: object) -> str:
    normalized = str(label or "").strip().lower().replace(" ", "_")
    if any(token in normalized for token in ("failed", "blocked", "unavailable", "error", "stale")):
        return "bad-state"
    if any(token in normalized for token in ("degraded", "await", "cash", "no_change", "pending", "partial", "idle")):
        return "warn-state"
    return "good-state"


def _pipeline_rows(
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
    operating_status: Any,
    holdings: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    briefing_status = str(briefing.get("status") or "Awaiting") if isinstance(briefing, Mapping) else "Awaiting"
    candidate = (
        str(briefing.get("candidate_identifier") or "No qualified candidate")
        if isinstance(briefing, Mapping)
        else "No governed CIO briefing yet"
    )
    decision = (
        str(briefing.get("portfolio_decision") or "No new action authorized")
        if isinstance(briefing, Mapping)
        else "Awaiting governed CIO decision"
    )
    if isinstance(construction, Mapping):
        construction_status = str(construction.get("status") or "Available")
        trade_count = len(construction.get("trades", ()) or ())
        construction_reason = f"{trade_count} proposed paper transaction{'s' if trade_count != 1 else ''}."
    else:
        construction_status = "Idle"
        construction_reason = "No construction change is queued."
    implementation_status = "Holding" if holdings else "Cash"
    implementation_reason = (
        f"{len(holdings)} current governed paper position{'s' if len(holdings) != 1 else ''}."
        if holdings
        else "The canonical portfolio currently holds cash only."
    )
    return [
        ("Operating evidence", str(getattr(operating_status, "label", "Unknown")), str(getattr(operating_status, "detail", "Operating status unavailable."))),
        ("Opportunity scope", briefing_status, candidate),
        ("Six-specialist / CIO synthesis", briefing_status, "Current governed analysis state feeding the sole CIO decision authority."),
        ("CIO decision", briefing_status, decision),
        ("Portfolio construction", construction_status, construction_reason),
        ("Paper implementation", implementation_status, implementation_reason),
    ]


def _pipeline_html(rows: list[tuple[str, str, str]]) -> tuple[str, str]:
    table: list[str] = []
    mobile: list[str] = []
    for stage, status, reason in rows:
        state_class = _status_class(status)
        badge = f'<span class="state {state_class}">{_esc(status)}</span>'
        table.append(
            f"<tr><td><strong>{_esc(stage)}</strong></td><td>{badge}</td><td>{_esc(reason)}</td></tr>"
        )
        mobile.append(
            '<div class="item"><div class="item-top">'
            f'<div class="item-title">{_esc(stage)}</div>{badge}</div>'
            f'<div class="item-sub">{_esc(reason)}</div></div>'
        )
    return "".join(table), "".join(mobile)


def _attention_items(
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
    operating_status: Any,
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for index, reason in enumerate(_construction_rejections(construction), start=1):
        rows.append((f"Construction block {index}", "Blocked", reason))

    label = str(getattr(operating_status, "label", "") or "")
    detail = str(getattr(operating_status, "detail", "") or "")
    if label and _status_class(label) != "good-state":
        rows.append(("Operating runtime", label, detail or "The operating path requires attention."))

    if not isinstance(briefing, Mapping):
        rows.append(("CIO briefing", "Awaiting", "The portfolio is awaiting a current governed CIO briefing."))
    else:
        watch = briefing.get("evidence_that_changes_conclusion", ())
        if isinstance(watch, (list, tuple)):
            for index, item in enumerate(watch[:4], start=1):
                text = str(item).strip()
                if text:
                    rows.append((f"Watch condition {index}", "Monitor", text))

    if not rows:
        rows.append(("Portfolio operating state", "Clear", "No unresolved operating or construction blocker is currently surfaced."))
    return rows[:12]


def _attention_html(rows: list[tuple[str, str, str]]) -> str:
    result: list[str] = []
    for title, status, reason in rows:
        result.append(
            '<div class="queue-item"><div class="queue-title">'
            f'<strong>{_esc(title)}</strong><span class="state {_status_class(status)}">{_esc(status)}</span>'
            f'</div><div class="queue-reason">{_esc(reason)}</div></div>'
        )
    return "".join(result)


def _command_center_html(
    *,
    totals: Mapping[str, Any],
    mandate: Mapping[str, Any],
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
    operating_status: Any,
) -> str:
    nav = _number(totals.get("nav", mandate.get("nav", 0.0)))
    cash = _number(totals.get("cash", mandate.get("cash", 0.0)))
    total_return = _number(totals.get("total_return", mandate.get("total_return", 0.0)))
    total_pnl = _number(totals.get("total_pnl", mandate.get("total_pnl", nav - _GENESIS_CAPITAL)))
    holdings = list(mandate.get("holdings", ()) or ())
    trades = list(mandate.get("trades", ()) or ())
    snapshots = list(mandate.get("snapshots", ()) or ())
    latest_snapshot = _latest_snapshot(snapshots)
    realized = _realized_pnl(trades, latest_snapshot)
    unrealized = _unrealized_pnl(holdings, latest_snapshot)
    deployed_amount = max(0.0, nav - cash)
    max_drawdown = abs(_drawdown(snapshots))
    as_of = mandate.get("as_of") or latest_snapshot.get("created_at")

    decision = (
        str(briefing.get("portfolio_decision") or "No new portfolio action authorized")
        if isinstance(briefing, Mapping)
        else str(getattr(operating_status, "headline", "Awaiting governed CIO decision"))
    )
    cio_status = (
        str(briefing.get("status") or getattr(operating_status, "label", "Awaiting"))
        if isinstance(briefing, Mapping)
        else str(getattr(operating_status, "label", "Awaiting"))
    )

    attribution = _attribution_html(_attribution_rows(holdings, trades))
    position_table, position_mobile = _positions_html(holdings)
    trade_items = "".join(_trade_item(item) for item in trades[:12]) or '<div class="muted">No paper trades have been recorded in this portfolio epoch.</div>'
    rejection_rows = _construction_rejections(construction)
    rejection_items = (
        "".join(
            '<div class="item"><div class="item-title">Construction / allocation block</div>'
            f'<div class="item-sub">{_esc(reason)}</div></div>'
            for reason in rejection_rows
        )
        or '<div class="muted">No current construction rejection is recorded.</div>'
    )
    pipeline_table, pipeline_mobile = _pipeline_html(
        _pipeline_rows(
            briefing=briefing,
            construction=construction,
            operating_status=operating_status,
            holdings=holdings,
        )
    )
    attention = _attention_html(
        _attention_items(
            briefing=briefing,
            construction=construction,
            operating_status=operating_status,
        )
    )
    equity = _equity_svg(snapshots)

    return f'''
<style>
  [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"], [data-testid="collapsedControl"] {{display:none !important;}}
  .block-container {{max-width:1480px !important;padding:18px clamp(12px,3vw,34px) 48px !important;}}
  .cie-command-center{{--bg:#071018;--panel:#0d1822;--panel2:#101f2b;--line:#203341;--text:#edf7fb;--muted:#8ea7b5;--good:#4ade80;--bad:#fb7185;--warn:#facc15;--accent:#67e8f9;--accent2:#38bdf8;--paper:#a78bfa;color:var(--text);font:14px/1.45 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
  .cie-command-center *{{box-sizing:border-box}} .cie-command-center .shell{{max-width:1440px;margin:0 auto}}
  .cie-command-center .top{{display:flex;gap:16px;justify-content:space-between;align-items:flex-start;margin-bottom:18px}} .cie-command-center .eyebrow{{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}} .cie-command-center .title{{font-size:clamp(24px,5vw,40px);font-weight:800;letter-spacing:-.035em;margin:4px 0 5px;color:var(--text)}} .cie-command-center .sub{{color:var(--muted);max-width:760px}}
  .cie-command-center .top-actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}} .cie-command-center .pill,.cie-command-center .btn{{border:1px solid var(--line);border-radius:999px;padding:8px 11px;background:#0a151e;color:var(--muted);font-weight:700;font-size:12px;text-decoration:none}} .cie-command-center .pill.paper{{color:#ddd6fe;border-color:#4c3b72;background:#171329}} .cie-command-center .pill.on{{color:#bbf7d0;border-color:#215836;background:#0b2115}} .cie-command-center .pill.off{{color:#fecdd3;border-color:#66303c;background:#251017}} .cie-command-center .btn{{color:var(--text)}}
  .cie-command-center .hero{{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,.8fr);gap:14px;margin-bottom:14px}} .cie-command-center .card{{background:linear-gradient(180deg,rgba(16,31,43,.96),rgba(11,24,34,.96));border:1px solid var(--line);border-radius:18px;box-shadow:0 18px 60px rgba(0,0,0,.18)}} .cie-command-center .hero-main{{padding:22px}} .cie-command-center .label{{color:var(--muted);font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}} .cie-command-center .nav{{font-size:clamp(38px,8vw,70px);font-weight:850;letter-spacing:-.055em;line-height:1;margin:10px 0 8px}} .cie-command-center .return{{font-size:18px;font-weight:800}} .cie-command-center .good{{color:var(--good)}} .cie-command-center .bad{{color:var(--bad)}} .cie-command-center .muted{{color:var(--muted)}}
  .cie-command-center .hero-side{{padding:18px;display:grid;gap:12px;align-content:center}} .cie-command-center .status-row{{display:flex;justify-content:space-between;gap:16px;padding-bottom:10px;border-bottom:1px solid var(--line)}} .cie-command-center .status-row:last-child{{border:0;padding-bottom:0}} .cie-command-center .status-val{{font-weight:800;text-align:right}}
  .cie-command-center .metrics{{display:grid;grid-template-columns:repeat(8,minmax(120px,1fr));gap:10px;margin-bottom:14px}} .cie-command-center .metric{{padding:14px}} .cie-command-center .metric .v{{font-size:19px;font-weight:800;margin-top:4px;white-space:nowrap}} .cie-command-center .metric .k{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em;font-weight:750}}
  .cie-command-center .grid2{{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,.8fr);gap:14px;margin-bottom:14px}} .cie-command-center .section{{padding:18px}} .cie-command-center .section-head{{display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin-bottom:14px}} .cie-command-center .section-title{{font-size:17px;font-weight:800}} .cie-command-center .section-note{{color:var(--muted);font-size:12px}} .cie-command-center .chart-wrap{{height:260px;position:relative}} .cie-command-center .chart-empty{{height:100%;display:grid;place-items:center;color:var(--muted)}} .cie-command-center .equity-svg{{width:100%;height:100%;display:block}} .cie-command-center .grid-line{{stroke:#203341;stroke-width:1}} .cie-command-center .genesis-line{{stroke:#475569;stroke-width:1;stroke-dasharray:5 5}} .cie-command-center .equity-line{{fill:none;stroke:#67e8f9;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}}
  .cie-command-center .attribution{{display:grid;gap:9px}} .cie-command-center .bar-row{{display:grid;grid-template-columns:minmax(110px,1fr) 2fr auto;gap:9px;align-items:center}} .cie-command-center .bar-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}} .cie-command-center .bar-track{{height:9px;border-radius:999px;background:#071019;overflow:hidden}} .cie-command-center .bar-fill{{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent2),var(--accent))}} .cie-command-center .bar-fill.neg{{background:linear-gradient(90deg,#fb7185,#f43f5e)}} .cie-command-center .bar-val{{font-variant-numeric:tabular-nums;font-weight:750}}
  .cie-command-center .full{{margin-bottom:14px}} .cie-command-center .table-wrap{{overflow:auto;border-radius:12px;border:1px solid var(--line)}} .cie-command-center table{{width:100%;border-collapse:collapse;min-width:720px}} .cie-command-center th,.cie-command-center td{{text-align:left;padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top}} .cie-command-center th{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);background:#0a151e;position:sticky;top:0}} .cie-command-center tbody tr:last-child td{{border-bottom:0}} .cie-command-center .num{{text-align:right;font-variant-numeric:tabular-nums}}
  .cie-command-center .state{{display:inline-flex;border-radius:999px;padding:4px 8px;font-size:10px;font-weight:850;letter-spacing:.04em;text-transform:uppercase;border:1px solid var(--line)}} .cie-command-center .state.good-state{{color:#bbf7d0;border-color:#215836}} .cie-command-center .state.warn-state{{color:#fde68a;border-color:#665c22}} .cie-command-center .state.bad-state{{color:#fecdd3;border-color:#66303c}}
  .cie-command-center .mobile-list{{display:none}} .cie-command-center .item{{padding:13px;border:1px solid var(--line);border-radius:13px;background:#0a151e;margin-bottom:8px}} .cie-command-center .item-top{{display:flex;justify-content:space-between;gap:10px}} .cie-command-center .item-title{{font-weight:800}} .cie-command-center .item-sub{{color:var(--muted);font-size:12px;margin-top:4px}} .cie-command-center .item-pnl{{font-weight:800;white-space:nowrap}}
  .cie-command-center .queue{{display:grid;gap:8px}} .cie-command-center .queue-item{{padding:12px;border:1px solid var(--line);border-radius:12px;background:#0a151e}} .cie-command-center .queue-title{{display:flex;gap:8px;align-items:center;justify-content:space-between}} .cie-command-center .queue-reason{{margin-top:6px;color:var(--muted)}} .cie-command-center .footer{{display:flex;justify-content:space-between;gap:15px;color:var(--muted);font-size:11px;padding-top:4px}}
  @media(max-width:1050px){{.cie-command-center .metrics{{grid-template-columns:repeat(4,1fr)}}.cie-command-center .hero,.cie-command-center .grid2{{grid-template-columns:1fr}}}}
  @media(max-width:650px){{.block-container{{padding-left:12px !important;padding-right:12px !important}}.cie-command-center .top{{display:block}}.cie-command-center .top-actions{{justify-content:flex-start;margin-top:12px}}.cie-command-center .hero-main,.cie-command-center .hero-side,.cie-command-center .section{{padding:15px}}.cie-command-center .metrics{{grid-template-columns:repeat(2,1fr)}}.cie-command-center .metric .v{{font-size:17px}}.cie-command-center .table-wrap{{display:none}}.cie-command-center .mobile-list{{display:block}}.cie-command-center .chart-wrap{{height:210px}}.cie-command-center .footer{{display:block}}.cie-command-center .footer>*{{margin-top:4px}}}}
</style>
<div class="cie-command-center"><div class="shell">
  <header class="top">
    <div><div class="eyebrow">Capital Intelligence</div><h1 class="title">Portfolio Command Center</h1><div class="sub">Canonical compounding paper account. The CIO alone authorizes portfolio changes; the screen makes current capital, decision state, blockers, and paper implementation immediately visible.</div></div>
    <div class="top-actions"><span class="pill paper">PAPER · $250K GENESIS</span><span class="pill on">AUTO PAPER EXECUTION · ON</span><span class="pill off">LIVE MONEY · DISABLED</span><a class="btn" href=".">Refresh</a></div>
  </header>

  <section class="hero">
    <div class="card hero-main"><div class="label">Current portfolio NAV</div><div class="nav">{_format_money(nav)}</div><div class="return {_pnl_class(total_return)}">{'+' if total_return > 0 else ''}{_format_pct(total_return)} since $250,000 genesis</div><div class="muted" style="margin-top:9px">Portfolio snapshot {_esc(_when(as_of))} · {_esc(decision)}</div></div>
    <div class="card hero-side"><div class="status-row"><span class="muted">Portfolio</span><span class="status-val">Canonical / persistent</span></div><div class="status-row"><span class="muted">Paper execution</span><span class="status-val good">Automatic</span></div><div class="status-row"><span class="muted">Live execution</span><span class="status-val bad">No authority</span></div><div class="status-row"><span class="muted">CIO state</span><span class="status-val">{_esc(cio_status.replace('_', ' ').title())}</span></div></div>
  </section>

  <section class="metrics">
    <div class="card metric"><div class="k">Starting capital</div><div class="v">$250,000</div></div><div class="card metric"><div class="k">Cash</div><div class="v">{_format_money(cash)}</div></div><div class="card metric"><div class="k">Deployed</div><div class="v">{_format_money(deployed_amount)}</div></div><div class="card metric"><div class="k">Total P&L</div><div class="v {_pnl_class(total_pnl)}">{_format_money(total_pnl)}</div></div><div class="card metric"><div class="k">Realized P&L</div><div class="v {_pnl_class(realized)}">{_format_money(realized)}</div></div><div class="card metric"><div class="k">Unrealized P&L</div><div class="v {_pnl_class(unrealized)}">{_format_money(unrealized)}</div></div><div class="card metric"><div class="k">Max drawdown</div><div class="v">{_format_pct(max_drawdown)}</div></div><div class="card metric"><div class="k">Open positions</div><div class="v">{len(holdings)}</div></div>
  </section>

  <section class="grid2"><div class="card section"><div class="section-head"><div class="section-title">Equity curve</div><div class="section-note">{len(snapshots)} NAV snapshots</div></div><div class="chart-wrap">{equity}</div></div><div class="card section"><div class="section-head"><div class="section-title">P&L attribution</div><div class="section-note">Current + realized</div></div><div class="attribution">{attribution}</div></div></section>

  <section class="card section full"><div class="section-head"><div class="section-title">Open paper positions</div><div class="section-note">Current governed holdings and marks</div></div><div class="table-wrap"><table><thead><tr><th>Instrument</th><th class="num">Quantity</th><th class="num">Cost basis</th><th class="num">Mark</th><th class="num">Market value</th><th class="num">Unrealized P&L</th><th class="num">Return</th><th>Updated</th></tr></thead><tbody>{position_table}</tbody></table></div><div class="mobile-list">{position_mobile}</div></section>

  <section class="grid2"><div class="card section"><div class="section-head"><div class="section-title">Recent paper trades</div><div class="section-note">Implementation history</div></div><div>{trade_items}</div></div><div class="card section"><div class="section-head"><div class="section-title">Skipped / rejected allocations</div><div class="section-note">Fail-closed reasons</div></div><div>{rejection_items}</div></div></section>

  <section class="card section full"><div class="section-head"><div class="section-title">Decision pipeline status</div><div class="section-note">Evidence → specialists → CIO → construction → paper implementation</div></div><div class="table-wrap"><table><thead><tr><th>Stage</th><th>Status</th><th>Current reason</th></tr></thead><tbody>{pipeline_table}</tbody></table></div><div class="mobile-list">{pipeline_mobile}</div></section>

  <section class="card section full"><div class="section-head"><div class="section-title">What needs attention next</div><div class="section-note">Current operating, evidence, and construction blockers</div></div><div class="queue">{attention}</div></section>

  <footer class="footer"><div>Auto-refresh: 30 seconds · Source: canonical portfolio and governed CIO journal</div><div>Paper-only system · CIO-only authority · no live-money execution</div></footer>
</div></div>
'''


@st.fragment(run_every="30s")
def _render_portfolio_command_center(dependencies, app_impl_module=None) -> None:
    totals = dependencies.get_portfolio_totals()
    mandate = dependencies.get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    if not isinstance(mandate, dict):
        st.error("The canonical paper portfolio is unavailable.")
        return

    briefing = None
    construction = None
    if app_impl_module is not None:
        try:
            briefing = app_impl_module._latest("daily_cio_briefing")
            construction = app_impl_module._latest("portfolio_construction")
        except (AttributeError, RuntimeError, OSError):
            briefing = None
            construction = None
    operating_status = load_cio_operating_status()
    st.markdown(
        _command_center_html(
            totals=totals,
            mandate=mandate,
            briefing=briefing if isinstance(briefing, Mapping) else None,
            construction=construction if isinstance(construction, Mapping) else None,
            operating_status=operating_status,
        ),
        unsafe_allow_html=True,
    )


def install(app_impl_module, secure_app_module) -> None:
    """Replace the navigation-heavy production surface with the command center."""

    if not portfolio_only_enabled():
        return

    def render_surfaces(*, dependencies=None, principal=None) -> None:
        del principal
        resolved = dependencies or app_impl_module.default_dependencies()
        st.session_state["dark_mode"] = True
        apply_global_style(dark_mode=True)
        _render_portfolio_command_center(resolved, app_impl_module=app_impl_module)

    def render_identity_controls(_principal: Any) -> None:
        # Authentication remains enforced by the secure application boundary. The
        # crypto-style production command center intentionally has no sidebar chrome.
        return

    def render_deployment_controls(_principal: Any, _deployment: Any) -> None:
        return

    app_impl_module.render_surfaces = render_surfaces
    secure_app_module.render_surfaces = render_surfaces
    secure_app_module._render_identity_controls = render_identity_controls
    secure_app_module._render_deployment_controls = render_deployment_controls


__all__ = [
    "_attention_items",
    "_command_center_html",
    "_deployed",
    "_drawdown",
    "_pipeline_rows",
    "install",
    "portfolio_only_enabled",
]
