"""Coordinate complete all-market evidence through fresh finite stage interpreters.

The coordinator is intentionally lightweight. It imports no provider, discovery, market
history, or paper-evidence stack. Each required evidence stage runs as a child process in
the same exclusive heavy-memory lane, commits its durable checkpoint, exits, and releases
its working set before the next stage begins.

A retry resumes the same still-fresh evidence epoch from the first incomplete stage. No
stage can be skipped, reordered, or treated as certified merely because the coordinator
survived. Missing or failed work remains fail-closed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

from operations.stage_isolated_evidence_pipeline import (
    _STAGES,
    ensure_stage_isolated_evidence_pipeline,
    load_stage_isolated_evidence_state,
)


_FAILURE_EVENT = "continuous_evidence_plane_failure_context"
_DAG_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"


def _safe_failure(
    *,
    pipeline_id: str,
    stage: str,
    return_code: int,
    error_type: str | None,
    error_detail: str | None,
) -> None:
    detail = (
        f"stage_isolated_evidence_failure; stage={stage}; return_code={return_code}; "
        f"child_error_type={error_type or 'StageProcessError'}; "
        f"child_detail={error_detail or 'stage process exited before durable completion'}"
    )[:1600]
    print(
        json.dumps(
            {
                "event": _FAILURE_EVENT,
                "error_type": error_type or "StageProcessError",
                "failure_stage": f"stage_isolated_evidence:{stage}",
                "error_detail": detail,
                "pipeline_id": pipeline_id,
                "credential_safe": True,
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "construction_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )


def run_pipeline(values: Mapping[str, str] | None = None) -> int:
    resolved = dict(os.environ if values is None else values)
    if str(resolved.get("RENDER") or "").strip().lower() == "true":
        # The stage coordinator already owns the single exclusive heavy-memory lane.
        # Comprehensive discovery keeps every required DAG node but executes lane workers
        # serially so nested interpreters cannot recreate a parallel memory spike.
        resolved[_DAG_WORKERS_ENV] = "1"
        os.environ[_DAG_WORKERS_ENV] = "1"

    state = ensure_stage_isolated_evidence_pipeline(resolved)
    if state.state == "completed" and state.generation_id:
        print(
            json.dumps(
                {
                    "event": "stage_isolated_evidence_pipeline_current",
                    "pipeline_id": state.pipeline_id,
                    "generation_id": state.generation_id,
                    "evidence_as_of": state.evidence_as_of.isoformat(),
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    script = Path(__file__).resolve().with_name("run_stage_isolated_evidence_stage.py")
    while True:
        state = load_stage_isolated_evidence_state(resolved)
        if state is None:
            raise RuntimeError("stage-isolated evidence state disappeared during execution")
        if state.state == "completed":
            if not state.generation_id:
                raise RuntimeError("completed stage-isolated pipeline has no generation id")
            print(
                json.dumps(
                    {
                        "event": "stage_isolated_evidence_pipeline_completed",
                        "pipeline_id": state.pipeline_id,
                        "generation_id": state.generation_id,
                        "evidence_as_of": state.evidence_as_of.isoformat(),
                        "completed_stages": list(state.completed_stages),
                        "all_required_stages_complete": state.completed_stages == _STAGES,
                        "paper_only": True,
                        "real_money_authorized": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return 0

        stage = state.next_stage
        if stage is None:
            raise RuntimeError("stage-isolated evidence pipeline has no runnable next stage")
        print(
            json.dumps(
                {
                    "event": "stage_isolated_evidence_stage_starting",
                    "pipeline_id": state.pipeline_id,
                    "stage": stage,
                    "evidence_as_of": state.evidence_as_of.isoformat(),
                    "completed_stages": list(state.completed_stages),
                    "fresh_interpreter": True,
                    "exclusive_heavy_memory_lane_inherited": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        process = subprocess.Popen(
            (
                sys.executable,
                str(script),
                stage,
                "--pipeline-id",
                state.pipeline_id,
            ),
            env=resolved,
            cwd=str(script.parent),
            # Keep every stage in the coordinator's process group. The outer reclaimable
            # memory governor can therefore terminate the entire active stage tree safely.
            start_new_session=False,
        )
        return_code = int(process.wait())
        latest = load_stage_isolated_evidence_state(resolved)
        if return_code != 0:
            _safe_failure(
                pipeline_id=state.pipeline_id,
                stage=stage,
                return_code=return_code,
                error_type=None if latest is None else latest.error_type,
                error_detail=None if latest is None else latest.error_detail,
            )
            return return_code
        if (
            latest is None
            or latest.pipeline_id != state.pipeline_id
            or stage not in latest.completed_stages
        ):
            _safe_failure(
                pipeline_id=state.pipeline_id,
                stage=stage,
                return_code=2,
                error_type="StageCheckpointError",
                error_detail="stage process exited successfully without durable stage completion",
            )
            return 2


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        return run_pipeline()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": _FAILURE_EVENT,
                    "error_type": type(error).__name__,
                    "failure_stage": "stage_isolated_evidence_pipeline",
                    "error_detail": str(error)[:1600],
                    "credential_safe": True,
                    "decision_authority": False,
                    "execution_authority": False,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
