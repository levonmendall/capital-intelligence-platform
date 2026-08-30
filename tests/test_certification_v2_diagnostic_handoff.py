from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from operations import certification_runtime_state as runtime
from operations import qualified_paper_evidence as qualified
from operations.certification_runtime_state import CertificationRuntimeStateError


CUTOFF = datetime(2026, 8, 30, 15, 45, tzinfo=timezone.utc)


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-diagnostic-test",
        "CAPITAL_INTELLIGENCE_DIAGNOSTIC_ALLOW_COMPREHENSIVE_DISCOVERY": "true",
        "CAPITAL_INTELLIGENCE_RUN_COMPREHENSIVE_DISCOVERY": "true",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
        "CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE": "true",
    }


def test_release_child_is_narrow_certification_writer(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(runtime, "evidence_plane_enabled", lambda _values: True)
    values = _values(tmp_path)
    serving = dict(values)
    serving.pop("CAPITAL_INTELLIGENCE_DIAGNOSTIC_ALLOW_COMPREHENSIVE_DISCOVERY")
    serving.pop("CAPITAL_INTELLIGENCE_RUN_COMPREHENSIVE_DISCOVERY")
    assert runtime.certification_runtime_enabled(serving) is False

    partial = dict(values)
    partial["CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE"] = "false"
    assert runtime.certification_runtime_enabled(partial) is False
    assert runtime.certification_runtime_enabled(values) is True

    nonproduction = dict(values)
    nonproduction["CAPITAL_INTELLIGENCE_ENVIRONMENT"] = "development"
    assert runtime.certification_runtime_enabled(nonproduction) is False


def test_handoff_freezes_once_then_resolves_existing_cutoff(monkeypatch, tmp_path) -> None:
    values = _values(tmp_path)
    frozen: list[datetime] = []
    resolved: list[datetime] = []
    monkeypatch.setattr(qualified, "certification_runtime_enabled", lambda _values: True)
    monkeypatch.setattr(
        qualified,
        "freeze_certification_input",
        lambda *, cutoff, values: frozen.append(cutoff),
    )
    monkeypatch.setattr(
        qualified,
        "resolve_certification_for_cutoff",
        lambda cutoff, *, values: resolved.append(cutoff),
    )

    qualified._ensure_all_market_certification_input_for_cutoff(CUTOFF, values)
    assert frozen == [CUTOFF]
    assert resolved == []

    exact = qualified._certification_cutoff_ledger_path(CUTOFF, values)
    exact.parent.mkdir(parents=True, exist_ok=True)
    exact.write_text("{}\n", encoding="utf-8")
    qualified._ensure_all_market_certification_input_for_cutoff(CUTOFF, values)

    assert frozen == [CUTOFF]
    assert resolved == [CUTOFF]


def test_existing_bad_cutoff_is_not_replaced(monkeypatch, tmp_path) -> None:
    values = _values(tmp_path)
    exact = qualified._certification_cutoff_ledger_path(CUTOFF, values)
    exact.parent.mkdir(parents=True, exist_ok=True)
    exact.write_text("bad\n", encoding="utf-8")
    monkeypatch.setattr(qualified, "certification_runtime_enabled", lambda _values: True)

    def reject(*_args, **_kwargs):
        raise CertificationRuntimeStateError("cutoff ledger integrity mismatch")

    monkeypatch.setattr(qualified, "resolve_certification_for_cutoff", reject)

    def must_not_freeze(**_kwargs):
        raise AssertionError("existing cutoff must not be replaced")

    monkeypatch.setattr(qualified, "freeze_certification_input", must_not_freeze)
    with pytest.raises(CertificationRuntimeStateError, match="integrity mismatch"):
        qualified._ensure_all_market_certification_input_for_cutoff(CUTOFF, values)


def test_capability_cio_keeps_operating_snapshot(monkeypatch, tmp_path) -> None:
    snapshot = SimpleNamespace(snapshot_id="operating-snapshot", payload={})
    universe = SimpleNamespace(identifier="operating-universe", instruments=())
    operating = SimpleNamespace(snapshot_id=snapshot.snapshot_id, snapshot=snapshot, universe=universe)
    observed: list[datetime] = []

    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION", "true")
    monkeypatch.setattr(qualified, "load_capability_operating_evidence", lambda **_kwargs: operating)
    monkeypatch.setattr(
        qualified,
        "_ensure_all_market_certification_input_for_cutoff",
        lambda cutoff, _values: observed.append(cutoff),
    )

    actual_snapshot, actual_universe = qualified._qualified_snapshot_and_universe_for_cutoff(CUTOFF)
    assert actual_snapshot is snapshot
    assert actual_universe is universe
    assert observed == [CUTOFF]
