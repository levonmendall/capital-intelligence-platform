from __future__ import annotations

from operations import bounded_terminal_screening as screening


def test_cio_442_diversification_substages_map_to_governed_stage(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED", "true"
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))

    for phase in ("diversification_count", "diversification_apply"):
        screening._finalization_progress(
            phase,
            "international_equity",
            processed_records=45_286,
            total_records=45_286,
        )


def test_cio_442_progress_wrapper_preserves_existing_finalization_stage(monkeypatch):
    captured: list[str] = []

    def fake_record(stage, *, metrics=None, values=None):
        captured.append(stage)
        return None

    monkeypatch.setattr(
        screening,
        "_core_record_manual_cio_diagnostic_progress",
        fake_record,
    )

    screening.record_manual_cio_diagnostic_progress(
        "terminal_screening_finalize_release:international_equity",
        metrics={"processed_records": 45_286, "total_records": 45_286},
    )

    assert captured == ["terminal_screening_finalize_release:international_equity"]


def test_cio_442_progress_wrapper_maps_only_diversification_detail(monkeypatch):
    captured: list[str] = []

    def fake_record(stage, *, metrics=None, values=None):
        captured.append(stage)
        return None

    monkeypatch.setattr(
        screening,
        "_core_record_manual_cio_diagnostic_progress",
        fake_record,
    )

    for phase in ("diversification_count", "diversification_apply"):
        screening.record_manual_cio_diagnostic_progress(
            f"terminal_screening_finalize_{phase}:international_equity",
            metrics={"processed_records": 45_286, "total_records": 45_286},
        )

    assert captured == [
        "terminal_screening_finalize_diversification:international_equity",
        "terminal_screening_finalize_diversification:international_equity",
    ]
