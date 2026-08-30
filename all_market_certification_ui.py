"""Read-only all-market certification provenance for the canonical portfolio UI.

This refinement installs after the evidence-accumulation renderer. It attaches one
canonical certification envelope to the existing asset-class summary, then renders that
same object in both the command-center header and evidence panel. It cannot advance
certification or authorize any investment, construction, paper, or live-money action.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from operations.all_market_certification_envelope import (
    load_all_market_certification_envelope,
)


_ORIGINAL_LOADER_ATTR = "_all_market_certification_original_status_loader"
_ORIGINAL_RENDERER_ATTR = "_all_market_certification_original_command_center_html"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _short(value: object, length: int = 8) -> str:
    text = str(value or "").strip()
    if not text:
        return "unavailable"
    return text if len(text) <= length else text[:length]


def _when(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "cutoff unavailable"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%b %d, %-I:%M %p")


def _coverage(envelope: Mapping[str, Any]) -> tuple[int, int]:
    raw = envelope.get("coverage")
    coverage = raw if isinstance(raw, Mapping) else {}
    try:
        represented = max(0, int(coverage.get("represented_count", 0) or 0))
    except (TypeError, ValueError):
        represented = 0
    try:
        required = max(0, int(coverage.get("required_count", 0) or 0))
    except (TypeError, ValueError):
        required = 0
    return represented, required


def certification_identity_text(envelope: Mapping[str, Any] | None) -> str:
    safe = envelope if isinstance(envelope, Mapping) else {}
    release = _short(safe.get("release_sha"))
    certification = _short(safe.get("certification_id"), 12)
    return f"Release {release} · Certificate {certification}"


def render_certification_banner(envelope: Mapping[str, Any] | None) -> str:
    """Render exact-release certification provenance without implying missing proof is green."""

    safe = envelope if isinstance(envelope, Mapping) else {}
    represented, required = _coverage(safe)
    certified = safe.get("certified") is True
    state = str(safe.get("certification_state") or "Unavailable").replace("_", " ").title()
    blocker = str(safe.get("blocker") or "").replace("_", " ")
    status = "All Markets Certified" if certified else "All-Market Certification Pending"
    tone = "good" if certified else "warn"
    count = f"{represented} / {required}" if required else f"{represented} / —"
    identity = certification_identity_text(safe)
    cutoff = _when(safe.get("evidence_cutoff"))
    verifier = _short(safe.get("verifier_source_id"), 20)
    detail = (
        f"{identity} · Evidence cutoff {cutoff} · Verifier {verifier}"
        if certified
        else f"{identity} · State {state} · {blocker or 'proof incomplete'}"
    )
    return (
        '<section class="certification-provenance" aria-label="All-market certification provenance">'
        '<div class="certification-provenance-main">'
        f'<span class="certification-provenance-status {tone}">{_esc(status)}</span>'
        f'<strong>{_esc(count)} governed markets represented</strong>'
        f'<span class="certification-provenance-detail">{_esc(detail)}</span>'
        '</div><div class="certification-provenance-boundary">Read-only proof · paper-only authority</div>'
        "</section>"
    )


def inject_certification_provenance(
    base_html: str,
    envelope: Mapping[str, Any] | None,
) -> str:
    """Put one certificate identity in the header and the evidence component."""

    if 'class="certification-provenance"' in base_html:
        return base_html
    banner = render_certification_banner(envelope)
    style = '''
<style>
  .cie-command-center .certification-provenance{display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:14px;padding:13px 15px;border:1px solid #274252;border-radius:15px;background:#0a1720;color:var(--text)}
  .cie-command-center .certification-provenance-main{display:flex;gap:10px;align-items:center;flex-wrap:wrap;min-width:0}
  .cie-command-center .certification-provenance-status{display:inline-flex;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900;letter-spacing:.07em;text-transform:uppercase;border:1px solid}
  .cie-command-center .certification-provenance-status.good{color:#bbf7d0;border-color:#256b40;background:#0a2416}
  .cie-command-center .certification-provenance-status.warn{color:#fde68a;border-color:#665c22;background:#241f09}
  .cie-command-center .certification-provenance-detail,.cie-command-center .certification-provenance-boundary{color:var(--muted);font-size:11px}
  .cie-command-center .certification-provenance-boundary{white-space:nowrap}
  @media(max-width:650px){.cie-command-center .certification-provenance{display:block}.cie-command-center .certification-provenance-boundary{margin-top:7px;white-space:normal}}
</style>
'''
    refined = base_html
    hero = '<section class="hero">'
    index = refined.find(hero)
    if index >= 0:
        refined = refined[:index] + style + banner + "\n  " + refined[index:]
    else:
        refined = style + banner + refined

    safe = envelope if isinstance(envelope, Mapping) else {}
    identity = certification_identity_text(safe)
    evidence_marker = '<div class="evidence-readonly">Read-only progress · thresholds unchanged</div>'
    if evidence_marker in refined:
        evidence_replacement = (
            '<div class="evidence-readonly">Read-only progress · thresholds unchanged'
            f'<br><span>{_esc(identity)}</span></div>'
        )
        refined = refined.replace(evidence_marker, evidence_replacement, 1)
    return refined


def install(portfolio_runtime: Any) -> None:
    """Install one envelope producer and one provenance renderer on the canonical UI."""

    if hasattr(portfolio_runtime, _ORIGINAL_LOADER_ATTR):
        return

    original_loader: Callable[..., Any] = portfolio_runtime.load_asset_class_evaluation_status
    original_renderer: Callable[..., str] = portfolio_runtime._command_center_html
    setattr(portfolio_runtime, _ORIGINAL_LOADER_ATTR, original_loader)
    setattr(portfolio_runtime, _ORIGINAL_RENDERER_ATTR, original_renderer)

    def status_with_certification(*args: Any, **kwargs: Any) -> Any:
        loaded = original_loader(*args, **kwargs)
        summary = dict(loaded) if isinstance(loaded, Mapping) else {}
        summary["all_market_certification"] = load_all_market_certification_envelope()
        return summary

    def command_center_with_certification(*args: Any, **kwargs: Any) -> str:
        base_html = original_renderer(*args, **kwargs)
        summary = kwargs.get("asset_class_evaluation")
        envelope = (
            summary.get("all_market_certification")
            if isinstance(summary, Mapping)
            else None
        )
        return inject_certification_provenance(
            base_html,
            envelope if isinstance(envelope, Mapping) else None,
        )

    portfolio_runtime.load_asset_class_evaluation_status = status_with_certification
    portfolio_runtime._command_center_html = command_center_with_certification


__all__ = [
    "certification_identity_text",
    "inject_certification_provenance",
    "install",
    "render_certification_banner",
]
