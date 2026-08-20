"""Run stage-isolated continuous evidence in the exclusive heavy-memory lane.

The long-lived coordinator imports no provider or discovery stack. Each evidence pass now
contains a lightweight stage coordinator which launches reference, public-live, U.S.-equity
discovery, comprehensive discovery, paper evidence, and finalization in separate fresh
interpreters. Every successful stage commits durable evidence before exiting, so Python and
provider working sets return to the operating system between major phases.

The outer worker retains the reclaimable-aware service memory guard and the single
cross-process heavy-memory lease. Nested certification DAG nodes remain serialized on
Render. No required market, provider requirement, evidence rule, specialist, CIO,
construction, execution, or paper-only control is reduced.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Mapping, Sequence

from run_bounded_render_worker import WorkerSpec, _run_isolated_once, run_loop


_SPEC = WorkerSpec(
    name="continuous-evidence-plane",
    script="run_stage_isolated_evidence_pipeline.py",
    # Preserve the historical one-shot command contract used by release-prequalification
    # and runtime validation. The stage coordinator treats this only as an execution-mode
    # declaration; every internal required stage still runs exactly once per pass.
    arguments=("--once",),
    interval_env="CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_INTERVAL_SECONDS",
    default_interval_seconds=300.0,
    timeout_env="CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PASS_TIMEOUT_SECONDS",
    default_timeout_seconds=3600.0,
    default_initial_delay_seconds=30.0,
)
_DAG_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"
_FAILURE_EVENT = "continuous_evidence_plane_failure_context"


def _lane_wait_seconds(values: Mapping[str, str]) -> float:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MEMORY_LANE_WAIT_SECONDS",
        "300",
    ).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MEMORY_LANE_WAIT_SECONDS must be numeric"
        ) from error
    if value < 0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MEMORY_LANE_WAIT_SECONDS cannot be negative"
        )
    return value


def _bounded_evidence_values(values: Mapping[str, str]) -> dict[str, str]:
    """Serialize nested DAG workers on Render while preserving complete certification."""

    resolved = dict(values)
    if str(resolved.get("RENDER") or "").strip().lower() == "true":
        resolved[_DAG_WORKERS_ENV] = "1"
    return resolved


def _memory_failure_context(values: Mapping[str, str]) -> None:
    """Transport the exact governed memory trigger and active durable stage upstream."""

    import run_bounded_manual_cio_diagnostic as memory_watchdog
    from operations.stage_isolated_evidence_pipeline import (
        load_stage_isolated_evidence_state,
    )

    report = getattr(memory_watchdog, "_last_reclaimable_memory_report", None)
    safe_report = report if isinstance(report, Mapping) else {}
    try:
        state = load_stage_isolated_evidence_state(values)
    except Exception:
        state = None
    if state is None:
        stage = "unknown"
        pipeline_id = None
    else:
        stage = state.current_stage or state.next_stage or "finalize"
        pipeline_id = state.pipeline_id

    trigger = str(safe_report.get("trigger_reason") or "unknown")
    detail = (
        f"stage_isolated_evidence_resource_boundary; stage={stage}; "
        f"trigger_reason={trigger}; "
        f"working_set_peak_kib={safe_report.get('container_peak_working_set_kib')}; "
        f"raw_peak_kib={safe_report.get('container_peak_memory_kib')}; "
        f"inactive_file_peak_kib={safe_report.get('container_peak_inactive_file_kib')}; "
        f"anon_peak_kib={safe_report.get('container_peak_anon_kib')}; "
        f"file_peak_kib={safe_report.get('container_peak_file_kib')}; "
        f"kernel_peak_kib={safe_report.get('container_peak_kernel_kib')}; "
        f"memory_accounting_source={safe_report.get('memory_accounting_source')}"
    )[:1600]
    print(
        json.dumps(
            {
                "event": _FAILURE_EVENT,
                "error_type": "ResourceBoundaryExceeded",
                "failure_stage": f"stage_isolated_evidence:{stage}",
                "error_detail": detail,
                "pipeline_id": pipeline_id,
                "memory_trigger_reason": trigger,
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


def run_continuous_once(values: Mapping[str, str] | None = None) -> int:
    resolved = _bounded_evidence_values(os.environ if values is None else values)
    return_code = _run_isolated_once(
        _SPEC,
        values=resolved,
        lane_wait_seconds=_lane_wait_seconds(resolved),
    )
    if return_code == 125:
        _memory_failure_context(resolved)
    return return_code


def run_continuous_loop(
    *,
    values: Mapping[str, str] | None = None,
    initial_delay_seconds: float | None = None,
) -> int:
    resolved = _bounded_evidence_values(os.environ if values is None else values)
    return run_loop(
        _SPEC,
        values=resolved,
        initial_delay_seconds=initial_delay_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.once:
            return run_continuous_once()
        return run_continuous_loop()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "continuous_evidence_plane_coordinator_failed",
                    "error_type": type(error).__name__,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())