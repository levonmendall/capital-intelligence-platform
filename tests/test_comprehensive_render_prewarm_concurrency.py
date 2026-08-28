from __future__ import annotations

import run_stage_isolated_evidence_stage as runtime


def test_render_comprehensive_prewarm_uses_six_bounded_workers(monkeypatch) -> None:
    monkeypatch.delenv(runtime._DAG_WORKERS_ENV, raising=False)
    values = {
        "RENDER": "true",
        runtime._DAG_WORKERS_ENV: "1",
    }

    runtime._configure_render_dag_workers(values)

    assert runtime._RENDER_DAG_WORKERS == "6"
    assert values[runtime._DAG_WORKERS_ENV] == "6"
    assert runtime.os.environ[runtime._DAG_WORKERS_ENV] == "6"


def test_non_render_comprehensive_prewarm_does_not_override_worker_count(monkeypatch) -> None:
    monkeypatch.setenv(runtime._DAG_WORKERS_ENV, "9")
    values = {
        "RENDER": "false",
        runtime._DAG_WORKERS_ENV: "7",
    }

    runtime._configure_render_dag_workers(values)

    assert values[runtime._DAG_WORKERS_ENV] == "7"
    assert runtime.os.environ[runtime._DAG_WORKERS_ENV] == "9"
