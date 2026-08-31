"""Bind the Portfolio Command Center to one exact-release production-state envelope.

This installer is deliberately presentation-only. It replaces independently sampled UI
readers with one durable read-only envelope per render and makes current production state,
asset-class progress, certification provenance, and historical fallback visibly distinct.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from operating_status import CIOOperatingStatus
from operations.production_state_envelope import load_production_state_envelope
from ui_reporting_time import format_reporting_timestamp


_ORIGINAL_OPERATING_ATTR = "_production_state_original_operating_loader"
_ORIGINAL_ASSET_ATTR = "_production_state_original_asset_loader"
_ORIGINAL_RENDERER_ATTR = "_production_state_original_command_center_html"
_PENDING_ENVELOPE_ATTR = "_production_state_pending_render_envelope"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _short(value: object, length: int = 8) -> str:
    text = str(value or "").strip()
    if not text:
        return "unavailable"
    return text if len(text) <= length else text[:length]


def _human(value: object, *, missing: str = "Not published") -> str:
    text = str(value or "").strip()
    return missing if not text else text.replace("_", " ").strip().title()


def _when(value: object, *, missing: str = "not published") -> str:
    return format_reporting_timestamp(value, missing=missing)


def _parse_utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _counts(summary: Mapping[str, Any] | None) -> tuple[int, int, int, int, int]:
    if not isinstance(summary, Mapping):
        return 0, 0, 0, 0, 0
    raw_rows = summary.get("rows")
    rows = [item for item in raw_rows if isinstance(item, Mapping)] if isinstance(raw_rows, list) else []
    total = int(summary.get("total") or summary.get("attempted") or len(rows) or 0)
    reached = int(summary.get("reached") or 0)
    evaluated = sum(str(row.get("status") or "").lower() == "evaluated" for row in rows)
    in_progress = sum(str(row.get("status") or "").lower() == "in progress" for row in rows)
    failed = sum(str(row.get("status") or "").lower() == "failed" for row in rows)
    return total, reached, evaluated, in_progress, failed


def _operating_from_envelope(
    envelope: Mapping[str, Any],
    fallback: CIOOperatingStatus,
) -> CIOOperatingStatus:
    production_raw = envelope.get("production")
    production = production_raw if isinstance(production_raw, Mapping) else {}
    release_matches = production.get("release_matches") is True
    if not release_matches:
        if str(production.get("state") or "") == "stale_release":
            return CIOOperatingStatus(
                state="degraded",
                label="Production state stale",
                headline="Exact-release production state is not yet published",
                detail=str(production.get("detail") or "The durable diagnostic belongs to another release."),
                observed_at=_parse_utc(envelope.get("observed_at")),
                cycle_status=fallback.cycle_status,
                cycle_key=fallback.cycle_key,
                next_retry_at=fallback.next_retry_at,
                last_briefing_at=fallback.last_briefing_at,
                release=str(envelope.get("release_sha") or fallback.release),
            )
        return fallback

    raw_state = str(production.get("state") or "unknown").strip().lower()
    if raw_state in {"pending", "in_progress"}:
        state = "processing"
        label = "Production evaluating"
    elif raw_state == "failed":
        state = "degraded"
        label = "Production evaluation failed"
    elif raw_state == "completed":
        state = "healthy"
        label = "Production evaluation complete"
    else:
        state = fallback.state
        label = fallback.label
    stage = _human(production.get("stage"), missing=fallback.headline)
    return CIOOperatingStatus(
        state=state,
        label=label,
        headline=stage,
        detail=str(production.get("detail") or fallback.detail),
        observed_at=_parse_utc(production.get("progress_recorded_at") or envelope.get("observed_at")),
        cycle_status=raw_state or fallback.cycle_status,
        cycle_key=str(production.get("cycle_key") or "") or fallback.cycle_key,
        next_retry_at=fallback.next_retry_at,
        last_briefing_at=fallback.last_briefing_at,
        release=str(envelope.get("release_sha") or fallback.release),
    )


def render_production_state_banner(summary: Mapping[str, Any] | None) -> str:
    """Render current system truth independently from certification success."""

    safe = summary if isinstance(summary, Mapping) else {}
    production_raw = safe.get("production_state")
    production = production_raw if isinstance(production_raw, Mapping) else {}
    alignment_raw = safe.get("production_alignment")
    alignment = alignment_raw if isinstance(alignment_raw, Mapping) else {}
    total, reached, evaluated, in_progress, failed = _counts(safe)
    release = _short(safe.get("release_sha") or production.get("release_sha"))
    state = _human(production.get("state"), missing="Not recorded")
    stage = _human(production.get("stage"), missing="Current stage not yet published")
    decision_epoch = _when(safe.get("decision_epoch"), missing="not published")
    observed = _when(production.get("progress_recorded_at") or production.get("observed_at"), missing="not published")
    exact = alignment.get("current_asset_state_exact_release") is True
    coherence = alignment.get("current_asset_state_coherent") is True
    scope_text = (
        f"{reached}/{total} lanes represented · {evaluated} evaluated · "
        f"{in_progress} in progress · {failed} failed"
        if total
        else "Current per-asset-class state not yet published"
    )
    truth = "Exact-release current state" if exact and coherence else "Current state incomplete"
    tone = "good" if exact and coherence and str(production.get("state") or "") == "completed" else "warn"
    return f'''
<style>
  .cie-command-center .production-state-envelope{{margin-bottom:14px;padding:14px 15px;border:1px solid #274252;border-radius:15px;background:#081821;color:var(--text)}}
  .cie-command-center .production-state-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
  .cie-command-center .production-state-kicker{{font-size:10px;font-weight:900;letter-spacing:.11em;text-transform:uppercase;color:#8fdff0}}
  .cie-command-center .production-state-stage{{font-size:16px;font-weight:850;margin-top:4px}}
  .cie-command-center .production-state-badge{{border:1px solid #665c22;background:#241f09;color:#fde68a;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900;text-transform:uppercase;white-space:nowrap}}
  .cie-command-center .production-state-badge.good{{border-color:#256b40;background:#0a2416;color:#bbf7d0}}
  .cie-command-center .production-state-meta{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px 14px;margin-top:10px;color:var(--muted);font-size:11px;line-height:1.45}}
  .cie-command-center .production-state-scope{{margin-top:9px;color:#d9edf5;font-size:12px}}
  @media(max-width:650px){{.cie-command-center .production-state-head{{display:block}}.cie-command-center .production-state-badge{{display:inline-flex;margin-top:8px}}.cie-command-center .production-state-meta{{grid-template-columns:1fr}}}}
</style>
<section class="production-state-envelope" aria-label="Current production state">
  <div class="production-state-head"><div><div class="production-state-kicker">Current production state</div><div class="production-state-stage">{_esc(stage)}</div></div><span class="production-state-badge {tone}">{_esc(truth)}</span></div>
  <div class="production-state-meta"><span>State {_esc(state)} · Release {_esc(release)}</span><span>Decision epoch {_esc(decision_epoch)}</span><span>Observed {_esc(observed)}</span><span>Read-only · paper-only authority</span></div>
  <div class="production-state-scope">{_esc(scope_text)}</div>
</section>
'''


def _inject_production_state(base_html: str, summary: Mapping[str, Any] | None) -> str:
    if 'class="production-state-envelope"' in base_html:
        return base_html
    safe = summary if isinstance(summary, Mapping) else {}
    source = str(safe.get("source") or "")
    historical = safe.get("historical") is True or source == "Latest completed global evaluation"
    certified = source == "Current all-market certification"
    refined = base_html
    if historical:
        refined = refined.replace("Certification evidence snapshot", "Historical evaluation snapshot", 1)
    elif not certified:
        refined = refined.replace("Certification evidence snapshot", "Evaluation evidence snapshot", 1)

    banner = render_production_state_banner(safe)
    cert_marker = '<section class="certification-provenance"'
    cert_index = refined.find(cert_marker)
    if cert_index >= 0:
        cert_end = refined.find("</section>", cert_index)
        if cert_end >= 0:
            cert_end += len("</section>")
            refined = refined[:cert_end] + "\n  " + banner + refined[cert_end:]
            return refined
    hero_marker = '<section class="hero">'
    hero_index = refined.find(hero_marker)
    if hero_index >= 0:
        return refined[:hero_index] + banner + "\n  " + refined[hero_index:]
    return banner + refined


def install(portfolio_runtime: Any) -> None:
    """Use exactly one production envelope for operating and asset state in each render."""

    if hasattr(portfolio_runtime, _ORIGINAL_ASSET_ATTR):
        return
    original_operating: Callable[..., CIOOperatingStatus] = portfolio_runtime.load_cio_operating_status
    original_asset: Callable[..., Any] = portfolio_runtime.load_asset_class_evaluation_status
    original_renderer: Callable[..., str] = portfolio_runtime._command_center_html
    setattr(portfolio_runtime, _ORIGINAL_OPERATING_ATTR, original_operating)
    setattr(portfolio_runtime, _ORIGINAL_ASSET_ATTR, original_asset)
    setattr(portfolio_runtime, _ORIGINAL_RENDERER_ATTR, original_renderer)

    def operating_loader(*args: Any, **kwargs: Any) -> CIOOperatingStatus:
        fallback = original_operating(*args, **kwargs)
        try:
            envelope = load_production_state_envelope()
        except (OSError, RuntimeError, TypeError, ValueError):
            return fallback
        setattr(portfolio_runtime, _PENDING_ENVELOPE_ATTR, envelope)
        return _operating_from_envelope(envelope, fallback)

    def asset_loader(*args: Any, **kwargs: Any) -> dict[str, object]:
        del args, kwargs
        envelope = getattr(portfolio_runtime, _PENDING_ENVELOPE_ATTR, None)
        if hasattr(portfolio_runtime, _PENDING_ENVELOPE_ATTR):
            delattr(portfolio_runtime, _PENDING_ENVELOPE_ATTR)
        if not isinstance(envelope, Mapping):
            envelope = load_production_state_envelope()
        raw = envelope.get("asset_class_evaluation")
        summary = dict(raw) if isinstance(raw, Mapping) else {}
        summary["release_sha"] = envelope.get("release_sha")
        summary["decision_epoch"] = envelope.get("decision_epoch")
        summary["production_state"] = envelope.get("production")
        summary["production_alignment"] = envelope.get("alignment")
        summary["previous_completed_evaluation"] = envelope.get("previous_completed_asset_class_evaluation")
        summary["all_market_certification"] = envelope.get("certification")
        return summary

    def renderer(*args: Any, **kwargs: Any) -> str:
        base_html = original_renderer(*args, **kwargs)
        raw = kwargs.get("asset_class_evaluation")
        return _inject_production_state(
            base_html,
            raw if isinstance(raw, Mapping) else None,
        )

    portfolio_runtime.load_cio_operating_status = operating_loader
    portfolio_runtime.load_asset_class_evaluation_status = asset_loader
    portfolio_runtime._command_center_html = renderer


__all__ = ["install", "render_production_state_banner"]
