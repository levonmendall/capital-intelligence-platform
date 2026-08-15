from __future__ import annotations

from pathlib import Path

import pytest

from operations.certification_state_machine import (
    CertificationState,
    CertificationStateError,
    advance_certification_state,
)


def _values(tmp_path: Path) -> dict[str, str]:
    return {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}


def test_state_machine_is_ordered_idempotent_and_append_only(tmp_path: Path) -> None:
    values = _values(tmp_path)
    evidence = advance_certification_state(
        certification_id="cert-test",
        target=CertificationState.EVIDENCE_READY,
        source_id="generation-test",
        values=values,
    )
    replay = advance_certification_state(
        certification_id="cert-test",
        target=CertificationState.EVIDENCE_READY,
        source_id="generation-test",
        values=values,
    )
    frozen = advance_certification_state(
        certification_id="cert-test",
        target=CertificationState.SNAPSHOT_FROZEN,
        source_id="snapshot-test",
        values=values,
    )

    assert replay.event_sha256 == evidence.event_sha256
    assert replay.path == evidence.path
    assert evidence.sequence == 1
    assert frozen.sequence == 2
    assert evidence.path.exists()
    assert frozen.path.exists()


def test_state_machine_rejects_skipped_prerequisite(tmp_path: Path) -> None:
    with pytest.raises(CertificationStateError, match="invalid certification transition"):
        advance_certification_state(
            certification_id="cert-test",
            target=CertificationState.SNAPSHOT_FROZEN,
            source_id="snapshot-test",
            values=_values(tmp_path),
        )


def test_state_machine_rejects_changed_source_on_idempotent_replay(
    tmp_path: Path,
) -> None:
    values = _values(tmp_path)
    advance_certification_state(
        certification_id="cert-test",
        target=CertificationState.EVIDENCE_READY,
        source_id="generation-a",
        values=values,
    )
    with pytest.raises(CertificationStateError, match="changed its source"):
        advance_certification_state(
            certification_id="cert-test",
            target=CertificationState.EVIDENCE_READY,
            source_id="generation-b",
            values=values,
        )


def test_construction_branches_to_implementation_or_no_action(tmp_path: Path) -> None:
    values = _values(tmp_path)
    path = (
        CertificationState.EVIDENCE_READY,
        CertificationState.SNAPSHOT_FROZEN,
        CertificationState.SCREENING_COMPLETE,
        CertificationState.COMMITTEE_COMPLETE,
        CertificationState.CIO_COMPLETE,
        CertificationState.CONSTRUCTION_COMPLETE,
        CertificationState.NO_ACTION,
        CertificationState.CERTIFIED,
    )
    for index, state in enumerate(path, start=1):
        result = advance_certification_state(
            certification_id="cert-no-action",
            target=state,
            source_id=f"source-{index}",
            values=values,
        )
    assert result.state is CertificationState.CERTIFIED
    assert result.sequence == len(path)
