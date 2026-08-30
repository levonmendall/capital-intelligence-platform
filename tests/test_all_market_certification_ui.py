from __future__ import annotations

from types import SimpleNamespace

import all_market_certification_ui as ui


def _envelope(*, certified: bool = True) -> dict[str, object]:
    return {
        "schema_version": "all-market-certification-envelope.v1",
        "certified": certified,
        "blocker": None if certified else "freshness_invalid",
        "release_sha": "abcdef1234567890",
        "certification_id": "certification-identity-123456",
        "certification_state": "CERTIFIED" if certified else "SCREENING_COMPLETE",
        "evidence_cutoff": "2026-08-30T21:30:00+00:00",
        "verifier_source_id": "certification-finalizer",
        "coverage": {
            "certified_count": 13 if certified else 0,
            "represented_count": 13,
            "required_count": 13,
            "complete": True,
        },
    }


def test_certified_provenance_is_visible_in_header_and_evidence_panel() -> None:
    base = (
        '<div class="cie-command-center"><header class="top">Header</header>'
        '<section class="hero">Hero</section>'
        '<div class="evidence-readonly">Read-only progress · thresholds unchanged</div>'
        '</div>'
    )

    rendered = ui.inject_certification_provenance(base, _envelope())

    assert "All Markets Certified" in rendered
    assert "13 / 13 governed markets represented" in rendered
    assert "Release abcdef12 · Certificate certificatio" in rendered
    assert rendered.count("Release abcdef12 · Certificate certificatio") == 2
    assert "paper-only authority" in rendered


def test_pending_provenance_never_uses_certified_label() -> None:
    rendered = ui.render_certification_banner(_envelope(certified=False))

    assert "All-Market Certification Pending" in rendered
    assert "All Markets Certified" not in rendered
    assert "freshness invalid" in rendered


def test_install_attaches_one_envelope_to_existing_summary_and_renderer(monkeypatch) -> None:
    envelope = _envelope()
    monkeypatch.setattr(ui, "load_all_market_certification_envelope", lambda: envelope)

    runtime = SimpleNamespace()
    runtime.load_asset_class_evaluation_status = lambda: {
        "attempted": 13,
        "successful": 13,
        "rows": [],
    }

    def base_renderer(*args, **kwargs):
        summary = kwargs["asset_class_evaluation"]
        assert summary["all_market_certification"] is envelope
        return (
            '<div class="cie-command-center">'
            '<section class="hero">Hero</section>'
            '<div class="evidence-readonly">Read-only progress · thresholds unchanged</div>'
            '</div>'
        )

    runtime._command_center_html = base_renderer
    ui.install(runtime)

    summary = runtime.load_asset_class_evaluation_status()
    assert summary["all_market_certification"] is envelope

    rendered = runtime._command_center_html(asset_class_evaluation=summary)
    assert "All Markets Certified" in rendered
    assert rendered.count("Release abcdef12 · Certificate certificatio") == 2

    first_loader = runtime.load_asset_class_evaluation_status
    first_renderer = runtime._command_center_html
    ui.install(runtime)
    assert runtime.load_asset_class_evaluation_status is first_loader
    assert runtime._command_center_html is first_renderer
