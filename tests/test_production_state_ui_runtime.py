from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from operating_status import CIOOperatingStatus
import production_state_ui_runtime as runtime_ui


_RELEASE = "e5cb07057c07f113adec8842215eb2b19046126e"
_EPOCH = "2026-08-31T03:31:00+00:00"


def _summary(source: str = "Current all-market evaluation") -> dict[str, object]:
    rows = [
        {
            "key": "us_equity",
            "asset_class": "U.S. equities",
            "status": "Evaluated",
            "detail": "10 cataloged · 10 deep analyzed · 1 selected",
        },
        {
            "key": "us_etf",
            "asset_class": "U.S. ETFs",
            "status": "In progress",
            "detail": "Screening in progress",
        },
    ]
    return {
        "source": source,
        "release_sha": _RELEASE,
        "decision_epoch": _EPOCH,
        "total": 13,
        "attempted": 13,
        "reached": 13,
        "successful": 1,
        "rows": rows,
        "exact_release": True,
        "historical": False,
        "production_state": {
            "state": "in_progress",
            "stage": "production_context_screening_graph_released",
            "detail": "screening graph active",
            "progress_recorded_at": "2026-08-31T03:59:00+00:00",
            "release_matches": True,
        },
        "production_alignment": {
            "current_asset_state_exact_release": True,
            "current_asset_state_coherent": True,
        },
    }


def _fallback() -> CIOOperatingStatus:
    return CIOOperatingStatus(
        state="healthy",
        label="CIO healthy",
        headline="Fallback health",
        detail="fallback",
        observed_at=datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc),
        release=_RELEASE,
    )


def test_banner_exposes_exact_release_stage_and_current_lane_counts() -> None:
    html = runtime_ui.render_production_state_banner(_summary())

    assert "Current production state" in html
    assert "Production Context Screening Graph Released" in html
    assert "Exact-release current state" in html
    assert "13/13 lanes represented" in html
    assert "1 evaluated" in html
    assert "1 in progress" in html
    assert "Read-only · paper-only authority" in html


def test_evaluation_snapshot_is_not_labeled_certification_snapshot() -> None:
    base = '<div class="cie-command-center"><div>Certification evidence snapshot Aug 30</div><section class="hero"></section></div>'
    refined = runtime_ui._inject_production_state(base, _summary())

    assert "Evaluation evidence snapshot" in refined
    assert "Certification evidence snapshot" not in refined
    assert "Current production state" in refined


def test_true_certification_retains_certification_snapshot_label() -> None:
    base = '<div class="cie-command-center"><div>Certification evidence snapshot Aug 30</div><section class="hero"></section></div>'
    summary = _summary("Current all-market certification")

    refined = runtime_ui._inject_production_state(base, summary)

    assert "Certification evidence snapshot" in refined
    assert "Evaluation evidence snapshot" not in refined


def test_historical_source_is_explicitly_historical() -> None:
    base = '<div class="cie-command-center"><div>Certification evidence snapshot Aug 30</div><section class="hero"></section></div>'
    summary = _summary("Latest completed global evaluation")
    summary["historical"] = True
    summary["exact_release"] = False
    summary["production_alignment"] = {
        "current_asset_state_exact_release": False,
        "current_asset_state_coherent": False,
    }

    refined = runtime_ui._inject_production_state(base, summary)

    assert "Historical evaluation snapshot" in refined
    assert "Current state incomplete" in refined


def test_install_uses_one_envelope_for_operating_and_asset_state(monkeypatch) -> None:
    calls: list[str] = []
    envelope = {
        "release_sha": _RELEASE,
        "decision_epoch": _EPOCH,
        "observed_at": "2026-08-31T04:00:00+00:00",
        "production": {
            "state": "in_progress",
            "stage": "production_context_screening_graph_released",
            "detail": "screening graph active",
            "progress_recorded_at": "2026-08-31T03:59:00+00:00",
            "release_matches": True,
            "cycle_key": "cycle-1",
        },
        "asset_class_evaluation": _summary(),
        "previous_completed_asset_class_evaluation": {
            "source": "Latest completed global evaluation",
            "historical": True,
        },
        "certification": {
            "release_sha": _RELEASE,
            "certified": False,
            "coverage": {"represented_count": 1, "required_count": 13},
        },
        "alignment": {
            "current_asset_state_exact_release": True,
            "current_asset_state_coherent": True,
        },
    }

    monkeypatch.setattr(
        runtime_ui,
        "load_production_state_envelope",
        lambda: calls.append("envelope") or envelope,
    )
    fake = SimpleNamespace(
        load_cio_operating_status=lambda: _fallback(),
        load_asset_class_evaluation_status=lambda: {"source": "legacy"},
        _command_center_html=lambda *args, **kwargs: (
            '<div class="cie-command-center">'
            '<section class="certification-provenance"></section>'
            '<div>Certification evidence snapshot Aug 30</div>'
            '</div>'
        ),
    )

    runtime_ui.install(fake)
    operating = fake.load_cio_operating_status()
    asset = fake.load_asset_class_evaluation_status()
    html = fake._command_center_html(asset_class_evaluation=asset)

    assert calls == ["envelope"]
    assert operating.state == "processing"
    assert operating.headline == "Production Context Screening Graph Released"
    assert asset["source"] == "Current all-market evaluation"
    assert asset["all_market_certification"] is envelope["certification"]
    assert asset["previous_completed_evaluation"] is envelope["previous_completed_asset_class_evaluation"]
    assert "Evaluation evidence snapshot" in html
    assert "Current production state" in html
