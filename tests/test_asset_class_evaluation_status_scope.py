from __future__ import annotations

from pathlib import Path
from typing import Any

import operations.asset_class_evaluation_status as status


_DECISION_EPOCH = "2026-08-30T23:06:00+00:00"
_RELEASE = "release-sha"
_CERTIFICATION = "certification-id"


def _terminal_summary(monkeypatch: Any, required_lanes: list[str]) -> dict[str, object]:
    aggregate_body = {
        "schema_version": status._CERT_SCHEMA,
        "certification_id": _CERTIFICATION,
        "release_sha": _RELEASE,
        "decision_epoch": _DECISION_EPOCH,
        "all_market_runtime_certified": True,
        "paper_only": True,
        "real_money_authorized": False,
        "required_lanes": required_lanes,
        "blocking_reasons": [],
    }
    aggregate = dict(aggregate_body)
    aggregate["sha256"] = status._digest(aggregate_body)
    pointer = {
        "release_sha": _RELEASE,
        "decision_epoch": _DECISION_EPOCH,
        "certification_id": _CERTIFICATION,
        "aggregate_sha256": aggregate["sha256"],
    }

    def fake_read(path: Path):
        if path.name == "latest.json":
            return pointer
        if path.name == "aggregate.json":
            return aggregate
        return None

    def evaluated_row(
        directory: Path,
        *,
        lane: str,
        certification_id: str,
        release_sha: str,
        decision_epoch: object,
        blocking_reasons: tuple[str, ...],
    ) -> dict[str, object]:
        del directory, certification_id, release_sha, decision_epoch, blocking_reasons
        return {
            "key": lane,
            "asset_class": lane,
            "status": "Evaluated",
            "detail": "1 cataloged · 1 deep analyzed · 1 selected",
        }

    monkeypatch.setattr(status, "_read_mapping", fake_read)
    monkeypatch.setattr(status, "_artifact_row", evaluated_row)
    result = status._terminal_evaluation_attempt(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/unused"},
        release_sha=_RELEASE,
        decision_epoch=_DECISION_EPOCH,
    )
    assert result is not None
    return result


def test_partial_certified_aggregate_cannot_claim_all_market_certification(monkeypatch):
    summary = _terminal_summary(monkeypatch, [status._GOVERNED_ASSET_CLASSES[0]])

    assert summary["source"] == "Current all-market evaluation"
    assert summary["reached"] == 1
    assert summary["successful"] == 1
    assert summary["total"] == len(status._GOVERNED_ASSET_CLASSES) == 13
    assert sum(row["status"] == "Awaiting evaluation" for row in summary["rows"]) == 12


def test_duplicate_scope_cannot_claim_all_market_certification(monkeypatch):
    lanes = list(status._GOVERNED_ASSET_CLASSES)
    lanes[-1] = lanes[0]

    summary = _terminal_summary(monkeypatch, lanes)

    assert summary["source"] == "Current all-market evaluation"
    assert summary["reached"] == 12


def test_exact_thirteen_lane_scope_can_claim_all_market_certification(monkeypatch):
    summary = _terminal_summary(monkeypatch, list(status._GOVERNED_ASSET_CLASSES))

    assert summary["source"] == "Current all-market certification"
    assert summary["reached"] == summary["successful"] == summary["total"] == 13
    assert all(row["status"] == "Evaluated" for row in summary["rows"])
