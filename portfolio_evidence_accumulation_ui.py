"""Crypto-style evidence accumulation presentation for Capital Intelligence.

This refinement replaces the legacy asset-class status table in the portfolio command
center with the same information hierarchy used by the Crypto Opportunity Engine: one
read-only synopsis followed by a full card for every governed asset class.

The module is presentation-only. It consumes the existing durable asset-class evaluation
read model, never contacts a provider, never changes a threshold, and cannot authorize a
CIO decision, construction change, paper transaction, or live-money action.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


_ORIGINAL_ATTR = "_evidence_accumulation_original_command_center_html"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _when(value: object) -> str:
    if value in (None, ""):
        return "No snapshot timestamp"
    text = str(value).strip()
    if not text:
        return "No snapshot timestamp"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%b %d, %-I:%M %p")


def _evaluation_rows(summary: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    raw_rows = summary.get("rows", ()) if isinstance(summary, Mapping) else ()
    if not isinstance(raw_rows, (list, tuple)):
        return ()
    return tuple(row for row in raw_rows if isinstance(row, Mapping))


def _status_key(status: object) -> str:
    return str(status or "").strip().lower()


def _summary_counts(summary: Mapping[str, Any] | None) -> dict[str, int]:
    rows = _evaluation_rows(summary)
    statuses = tuple(_status_key(row.get("status")) for row in rows)
    total = max(
        len(rows),
        _int(summary.get("total") if isinstance(summary, Mapping) else None),
        _int(summary.get("attempted") if isinstance(summary, Mapping) else None),
    )
    evaluated = sum(status == "evaluated" for status in statuses)
    failed = sum(status == "failed" for status in statuses)
    in_progress = sum(status == "in progress" for status in statuses)
    awaiting = sum(status == "awaiting evaluation" for status in statuses)
    reached_fallback = sum(status != "awaiting evaluation" for status in statuses)
    reached = _int(summary.get("reached") if isinstance(summary, Mapping) else None, reached_fallback)
    reached = max(0, min(total, reached if reached or not rows else reached_fallback))
    return {
        "total": total,
        "reached": reached,
        "evaluated": evaluated,
        "in_progress": in_progress,
        "awaiting": awaiting,
        "failed": failed,
    }


def _detail_count(detail: object, label: str) -> str:
    """Read a published count from canonical human-readable lane detail, if present."""

    text = str(detail or "")
    suffix = f" {label.lower()}"
    for fragment in text.split("·"):
        candidate = fragment.strip()
        lowered = candidate.lower()
        if not lowered.endswith(suffix):
            continue
        number = candidate[: -len(suffix)].strip()
        if number.isdigit():
            return number
    return "—"


def _status_tone(status: object) -> str:
    normalized = _status_key(status)
    if normalized == "evaluated":
        return "good"
    if normalized == "failed":
        return "bad"
    return "warn"


def _next_step(status: object) -> str:
    normalized = _status_key(status)
    if normalized == "evaluated":
        return "Maintain current evidence; the next governed cycle will refresh this asset class."
    if normalized == "failed":
        return "Repair the surfaced evaluation blocker and rerun without lowering evidence or decision thresholds."
    if normalized == "in progress":
        return "Continue the governed evaluation until terminal evidence is published."
    return "Await the governed evaluation path; thresholds remain unchanged."


def _asset_class_card(row: Mapping[str, Any]) -> str:
    asset_class = str(row.get("asset_class") or row.get("key") or "Unknown asset class")
    status = str(row.get("status") or "Awaiting evaluation")
    detail = str(row.get("detail") or "No additional evaluation detail is available.")
    normalized = _status_key(status)
    reached = normalized != "awaiting evaluation"
    terminal = normalized in {"evaluated", "failed"}
    evaluated = normalized == "evaluated"
    tone = _status_tone(status)

    metrics = (
        ("Cataloged", _detail_count(detail, "cataloged"), "published universe count"),
        ("Deep analyzed", _detail_count(detail, "deep analyzed"), "published deep-analysis count"),
        ("Selected", _detail_count(detail, "selected"), "published selected count"),
        ("Reached", "Yes" if reached else "No", "current governed evaluation"),
        ("Terminal", "Yes" if terminal else "No", "terminal result published"),
        ("Evaluated", "Yes" if evaluated else "No", "successful terminal evaluation"),
    )
    metric_html = "".join(
        '<div class="evidence-metric">'
        f'<div class="evidence-metric-label">{_esc(label)}</div>'
        f'<div class="evidence-metric-value">{_esc(value)}</div>'
        f'<div class="evidence-metric-sub">{_esc(subtitle)}</div>'
        "</div>"
        for label, value, subtitle in metrics
    )

    return (
        '<article class="asset-evidence-card">'
        '<div class="asset-evidence-head"><div>'
        f'<div class="asset-evidence-title">{_esc(asset_class)}</div>'
        '<div class="asset-evidence-subtitle">Comprehensive asset-class evaluation</div>'
        f'</div><span class="evidence-status evidence-status-{tone}">{_esc(status)}</span></div>'
        f'<div class="asset-evidence-metrics">{metric_html}</div>'
        f'<div class="asset-evidence-detail">{_esc(detail)}</div>'
        f'<div class="asset-evidence-next"><strong>Next:</strong> {_esc(_next_step(status))}</div>'
        "</article>"
    )


def render_evidence_accumulation(summary: Mapping[str, Any] | None) -> str:
    """Render the read-only synopsis and every governed asset-class card."""

    safe_summary = summary if isinstance(summary, Mapping) else {}
    rows = _evaluation_rows(safe_summary)
    counts = _summary_counts(safe_summary)
    source = str(safe_summary.get("source") or "No comprehensive evaluation recorded")
    as_of = _when(safe_summary.get("as_of"))

    tiles = (
        ("Governed classes", str(counts["total"]), "complete evaluation scope"),
        ("Reached now", f'{counts["reached"]} / {counts["total"]}', "current source has reached"),
        ("Evaluated", f'{counts["evaluated"]} / {counts["total"]}', "successful terminal evaluation"),
        ("In progress", str(counts["in_progress"]), "terminal result pending"),
        ("Awaiting", str(counts["awaiting"]), "not reached by current source"),
        ("Failed", str(counts["failed"]), "terminal blocker surfaced"),
    )
    tile_html = "".join(
        '<div class="evidence-summary-tile">'
        f'<div class="evidence-summary-label">{_esc(label)}</div>'
        f'<div class="evidence-summary-value">{_esc(value)}</div>'
        f'<div class="evidence-summary-sub">{_esc(subtitle)}</div>'
        "</div>"
        for label, value, subtitle in tiles
    )
    cards = "".join(_asset_class_card(row) for row in rows)
    if not cards:
        cards = (
            '<article class="asset-evidence-card">'
            '<div class="asset-evidence-title">Asset-class evidence unavailable</div>'
            '<div class="asset-evidence-detail">No comprehensive asset-class evaluation has been recorded yet.</div>'
            '<div class="asset-evidence-next"><strong>Next:</strong> Await the governed evaluation path; thresholds remain unchanged.</div>'
            "</article>"
        )

    return f'''
<style>
  .cie-command-center .evidence-accumulation{{margin-bottom:14px}}
  .cie-command-center .evidence-synopsis{{padding:20px;margin-bottom:12px}}
  .cie-command-center .evidence-synopsis-head{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;margin-bottom:16px}}
  .cie-command-center .evidence-title{{font-size:clamp(22px,4vw,30px);font-weight:850;letter-spacing:-.025em;color:var(--text)}}
  .cie-command-center .evidence-subtitle{{color:var(--muted);font-size:13px;margin-top:4px;max-width:820px}}
  .cie-command-center .evidence-readonly{{color:var(--muted);font-size:12px;line-height:1.45;text-align:right;max-width:230px}}
  .cie-command-center .evidence-summary-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}
  .cie-command-center .evidence-summary-tile,.cie-command-center .evidence-metric{{background:#08141d;border:1px solid #264052;border-radius:14px;padding:13px;min-width:0}}
  .cie-command-center .evidence-summary-label,.cie-command-center .evidence-metric-label{{color:#9bb2c0;font-size:10px;font-weight:850;letter-spacing:.1em;text-transform:uppercase}}
  .cie-command-center .evidence-summary-value{{font-size:25px;font-weight:850;line-height:1.1;margin-top:7px;color:var(--text)}}
  .cie-command-center .evidence-summary-sub,.cie-command-center .evidence-metric-sub{{color:var(--muted);font-size:11px;margin-top:4px}}
  .cie-command-center .asset-evidence-list{{display:grid;grid-template-columns:1fr;gap:10px}}
  .cie-command-center .asset-evidence-card{{background:linear-gradient(180deg,rgba(10,23,33,.99),rgba(7,18,27,.99));border:1px solid #244052;border-radius:18px;padding:17px}}
  .cie-command-center .asset-evidence-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:13px}}
  .cie-command-center .asset-evidence-title{{font-size:18px;font-weight:850;letter-spacing:-.015em;color:var(--text)}}
  .cie-command-center .asset-evidence-subtitle{{color:var(--muted);font-size:12px;margin-top:2px}}
  .cie-command-center .evidence-status{{display:inline-flex;align-items:center;border-radius:999px;padding:6px 10px;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;border:1px solid}}
  .cie-command-center .evidence-status-good{{color:#bbf7d0;border-color:#256b40;background:#0a2416}}
  .cie-command-center .evidence-status-warn{{color:#bae6fd;border-color:#23638a;background:#081d2b}}
  .cie-command-center .evidence-status-bad{{color:#fecdd3;border-color:#7a3443;background:#281018}}
  .cie-command-center .asset-evidence-metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}}
  .cie-command-center .evidence-metric{{padding:11px;border-radius:12px}}
  .cie-command-center .evidence-metric-value{{font-size:18px;font-weight:850;line-height:1.1;margin-top:6px;color:var(--text)}}
  .cie-command-center .asset-evidence-detail{{color:var(--muted);font-size:13px;line-height:1.5;margin-top:12px}}
  .cie-command-center .asset-evidence-next{{color:#d9edf5;font-size:13px;line-height:1.5;margin-top:5px}}
  @media(max-width:1050px){{.cie-command-center .asset-evidence-metrics{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}
  @media(max-width:650px){{.cie-command-center .evidence-synopsis{{padding:15px}}.cie-command-center .evidence-synopsis-head{{display:block}}.cie-command-center .evidence-readonly{{text-align:left;max-width:none;margin-top:8px}}.cie-command-center .evidence-summary-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.cie-command-center .asset-evidence-card{{padding:14px}}.cie-command-center .asset-evidence-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.cie-command-center .asset-evidence-head{{align-items:center}}.cie-command-center .asset-evidence-title{{font-size:17px}}}}
</style>
<section class="evidence-accumulation" aria-label="Asset class evidence accumulation">
  <div class="card evidence-synopsis">
    <div class="evidence-synopsis-head">
      <div><div class="evidence-title">Evidence accumulation</div><div class="evidence-subtitle">Certification evidence snapshot {_esc(as_of)} · {_esc(source)}</div></div>
      <div class="evidence-readonly">Read-only progress · thresholds unchanged</div>
    </div>
    <div class="evidence-summary-grid">{tile_html}</div>
  </div>
  <div class="asset-evidence-list">{cards}</div>
</section>
'''


def refine_command_center_html(
    base_html: str,
    summary: Mapping[str, Any] | None,
) -> str:
    """Replace the old evaluation table and place the evidence view after capital metrics."""

    if 'class="evidence-accumulation"' in base_html:
        return base_html

    refined = base_html
    old_title = '<div class="section-title">Asset class evaluation status</div>'
    title_index = refined.find(old_title)
    if title_index >= 0:
        section_start = refined.rfind("<section", 0, title_index)
        section_end = refined.find("</section>", title_index)
        if section_start >= 0 and section_end >= 0:
            section_end += len("</section>")
            refined = refined[:section_start] + refined[section_end:]

    evidence = render_evidence_accumulation(summary)
    metrics_start = refined.find('<section class="metrics">')
    if metrics_start < 0:
        return evidence + refined
    metrics_end = refined.find("</section>", metrics_start)
    if metrics_end < 0:
        return evidence + refined
    metrics_end += len("</section>")
    return refined[:metrics_end] + "\n\n  " + evidence + refined[metrics_end:]


def install(portfolio_runtime: Any) -> None:
    """Install the refinement once on the canonical portfolio command-center renderer."""

    if hasattr(portfolio_runtime, _ORIGINAL_ATTR):
        return
    original: Callable[..., str] = portfolio_runtime._command_center_html
    setattr(portfolio_runtime, _ORIGINAL_ATTR, original)

    def command_center_with_evidence(*args: Any, **kwargs: Any) -> str:
        base_html = original(*args, **kwargs)
        summary = kwargs.get("asset_class_evaluation")
        return refine_command_center_html(
            base_html,
            summary if isinstance(summary, Mapping) else None,
        )

    portfolio_runtime._command_center_html = command_center_with_evidence


__all__ = [
    "install",
    "refine_command_center_html",
    "render_evidence_accumulation",
]
