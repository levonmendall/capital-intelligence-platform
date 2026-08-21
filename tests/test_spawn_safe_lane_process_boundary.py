from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from operations import persistent_certification_scheduler as scheduler
from operations import spawn_safe_authoritative_acquisition as spawn_safe


def _node() -> scheduler.CertificationNode:
    timestamp = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
    return scheduler.CertificationNode(
        node_id="deep-market-evidence:international_equity",
        asset_class="international_equity",
        provider_groups=("eodhd", "massive", "twelve"),
        input_fingerprint="a" * 64,
        deadline=timestamp + timedelta(minutes=15),
        decision_eligible_count=123,
        priority=0,
    )


def test_lane_runner_launches_fresh_python_interpreter(tmp_path, monkeypatch) -> None:
    node = _node()
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    class FakeProcess:
        pid = 4242

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        calls.append((tuple(command), dict(kwargs)))
        return FakeProcess()

    monkeypatch.setattr(spawn_safe.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(spawn_safe, "_load_lane_result", lambda *_args, **_kwargs: 117)

    runner = spawn_safe.SpawnSafeSingleLaneRunner(
        manifest_path=str(tmp_path / "manifest.json"),
        node_id=node.node_id,
        timestamp=datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc),
        policy_version="policy.v1",
        environment=(("CAPITAL_INTELLIGENCE_RELEASE", "release-test"),),
    )

    assert runner(node) == 117
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[1:4] == (
        "-m",
        "operations.spawn_safe_authoritative_acquisition",
        "run-lane",
    )
    assert "--manifest" in command
    assert "--node-id" in command
    assert kwargs["start_new_session"] is False
    assert kwargs["env"]["CAPITAL_INTELLIGENCE_RELEASE"] == "release-test"


def test_spawn_safe_path_serializes_heavy_lane_processes() -> None:
    source = Path("operations/spawn_safe_authoritative_acquisition.py").read_text(
        encoding="utf-8"
    )
    start = source.index("def spawn_safe_acquire")
    end = source.index("\ndef _install_spool_aware_finalizer", start)
    body = source[start:end]

    assert 'scheduler_values[_SERIAL_LANE_WORKERS_ENV] = "1"' in body
    assert "environment=tuple(sorted" in body


def test_heavy_provider_probe_exists_only_behind_child_executor() -> None:
    source = Path("operations/spawn_safe_authoritative_acquisition.py").read_text(
        encoding="utf-8"
    )
    child_start = source.index("def _execute_lane_in_current_process")
    child_end = source.index("\n\n@dataclass", child_start)
    child_body = source[child_start:child_end]
    runner_start = source.index("class SpawnSafeSingleLaneRunner")
    runner_end = source.index("\n\n@dataclass", runner_start + 10)
    runner_body = source[runner_start:runner_end]

    assert "core.default_redundant_market_probe" in child_body
    assert "subprocess.Popen" in runner_body
    assert "core.default_redundant_market_probe" not in runner_body


def test_lane_result_transport_carries_no_investment_authority(tmp_path) -> None:
    node = _node()
    manifest_path = tmp_path / "manifest.json"
    result_path = spawn_safe._write_lane_result(
        manifest_path,
        node=node,
        evidence_complete_count=117,
    )

    body = spawn_safe._spool._load_json(
        result_path,
        schema=spawn_safe._LANE_RESULT_SCHEMA,
    )
    assert body["decision_authority"] is False
    assert body["candidate_authority"] is False
    assert body["sizing_authority"] is False
    assert body["construction_authority"] is False
    assert body["execution_authority"] is False
    assert body["paper_only"] is True
    assert body["real_money_authorized"] is False
