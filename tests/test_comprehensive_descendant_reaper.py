from __future__ import annotations

import json
from datetime import datetime, timezone

import operations.comprehensive_descendant_reaper as reaper


EPOCH = datetime(2026, 8, 31, 18, 51, 44, tzinfo=timezone.utc)
RELEASE = "release-1"


def _values(tmp_path):
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": RELEASE,
    }


def _write_runtime(tmp_path, *, pid=4242, start_ticks=9001, release=RELEASE):
    path = reaper._runtime_path(_values(tmp_path), release=release, epoch=EPOCH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "persistent-certification-runtime.v1",
                "release_sha": release,
                "decision_epoch": EPOCH.isoformat(),
                "policy_version": "policy",
                "updated_at": EPOCH.isoformat(),
                "required_nodes": ["deep-market-evidence:us_equity"],
                "counts": {
                    "completed_nodes": 0,
                    "reused_nodes": 0,
                    "failed_nodes": 0,
                    "running_nodes": 1,
                    "pending_nodes": 0,
                },
                "node_states": {
                    "deep-market-evidence:us_equity": {
                        "state": "running",
                        "asset_class": "us_equity",
                        "provider_groups": ["massive"],
                        "decision_eligible_count": 1,
                        "reused": False,
                        "failure_type": None,
                        "pid": pid,
                        "process_start_ticks": start_ticks,
                        "process_group_ready": True,
                    }
                },
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            }
        ),
        encoding="utf-8",
    )


def test_reaper_kills_only_exact_persisted_process_identity(tmp_path, monkeypatch) -> None:
    _write_runtime(tmp_path)
    calls = []
    monkeypatch.setattr(
        reaper,
        "_identity_alive",
        lambda pid, start_ticks: pid == 4242 and start_ticks == 9001,
    )

    def fake_terminate(pid, *, start_ticks, process_group_ready):
        calls.append((pid, start_ticks, process_group_ready))
        return True

    monkeypatch.setattr(reaper, "_terminate_exact_process", fake_terminate)
    report = reaper.reap_stale_comprehensive_descendants(
        _values(tmp_path),
        evidence_as_of=EPOCH,
        release=RELEASE,
    )
    assert calls == [(4242, 9001, True)]
    assert report["identity_matched"] == 1
    assert report["reaped"] == 1


def test_reaper_refuses_pid_reuse_identity_mismatch(tmp_path, monkeypatch) -> None:
    _write_runtime(tmp_path)
    monkeypatch.setattr(reaper, "_identity_alive", lambda pid, start_ticks: False)
    monkeypatch.setattr(
        reaper,
        "_terminate_exact_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not kill")),
    )
    report = reaper.reap_stale_comprehensive_descendants(
        _values(tmp_path),
        evidence_as_of=EPOCH,
        release=RELEASE,
    )
    assert report["reaped"] == 0
    assert report["identity_mismatch_or_gone"] == 1


def test_reaper_ignores_wrong_release_journal(tmp_path, monkeypatch) -> None:
    _write_runtime(tmp_path, release="other-release")
    monkeypatch.setattr(
        reaper,
        "_terminate_exact_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not kill")),
    )
    report = reaper.reap_stale_comprehensive_descendants(
        _values(tmp_path),
        evidence_as_of=EPOCH,
        release=RELEASE,
    )
    assert report["attempted"] is False
    assert report["reaped"] == 0
