from __future__ import annotations

from pathlib import Path

from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)


def test_release_prequalification_can_return_to_in_progress_before_final_capability_gate(
    tmp_path: Path,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-current",
    }
    ready = write_release_evidence_prequalification(
        values,
        state="completed",
        stage="evidence_generation_ready",
        detail="broad evidence ready",
        generation_id="generation-current",
        metrics={"complete_all_market_coverage_required": 1},
    )

    write_release_evidence_prequalification(
        values,
        state="in_progress",
        stage="evidence_refresh",
        prequalification_id=str(ready["prequalification_id"]),
        started_at=__import__("datetime").datetime.fromisoformat(str(ready["started_at"])),
        detail="qualifying additional capability evidence",
        generation_id="generation-current",
        metrics={
            "capability_operating_evidence_required": 1,
            "complete_all_market_coverage_required": 1,
        },
    )

    current = load_release_evidence_prequalification(values)
    assert current is not None
    assert current["state"] == "in_progress"
    assert current["stage"] == "evidence_refresh"
    assert current["generation_id"] == "generation-current"
