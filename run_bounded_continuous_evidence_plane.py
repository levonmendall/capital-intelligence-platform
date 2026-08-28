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
    """Transport the governed memory trigger and exact active discovery unit upstream."""

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

    lane_context: Mapping[str, object] | None = None
    if state is not None and stage == "comprehensive_discovery":
        try:
            from operations.comprehensive_discovery_memory_attribution import (
                lane_local_memory_failure_context,
            )

            boundary = state.stage_started_at or state.evidence_as_of
            lane_context = lane_local_memory_failure_context(
                values,
                boundary=boundary,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            # Failure attribution is observability-only. Never obscure the governed
            # ResourceBoundaryExceeded event if its lane-local projection is unavailable.
            lane_context = None

    trigger = str(safe_report.get("trigger_reason") or "unknown")
    failure_stage = f"stage_isolated_evidence:{stage}"
    lane_detail = ""
    lane_fields: dict[str, object] = {}
    if lane_context is not None:
        progress_kind = str(lane_context.get("progress_kind") or "unknown")
        substage = str(lane_context.get("substage") or "unknown")
        asset_class = str(lane_context.get("asset_class") or "") or None
        component = str(lane_context.get("component") or "") or None
        lane_index = lane_context.get("active_lane_index")
        metrics = lane_context.get("metrics")
        safe_metrics = dict(metrics) if isinstance(metrics, Mapping) else {}
        lane_fields = {
            "failure_progress_kind": progress_kind,
            "failure_substage": substage,
            "failure_asset_class": asset_class,
            "failure_component": component,
            "failure_lane_index": lane_index,
            "lane_progress_metrics": safe_metrics,
        }
        if progress_kind == "active" and asset_class and substage in {
            "catalog-lane",
            "publication-lane",
            "screening-lane",
        }:
            # The coordinator writes the active marker immediately before launching the
            # finite child, so this is exact failure attribution rather than inference.
            failure_stage = (
                f"stage_isolated_evidence:{stage}:{substage}:{asset_class}"
            )
            lane_detail = (
                f"; lane_progress_kind=active; lane_substage={substage}; "
                f"lane_asset_class={asset_class}; active_lane_index={lane_index}; "
                f"lane_component={component}; lane_progress_metrics={safe_metrics}"
            )
        else:
            # A completed component is useful as a last durable checkpoint, but must not
            # be mislabeled as the unit that crossed the memory boundary.
            lane_fields["last_durable_progress_component"] = component
            lane_detail = (
                f"; lane_progress_kind={progress_kind}; "
                f"last_durable_component={component}; "
                f"last_durable_asset_class={asset_class}; "
                f"lane_progress_metrics={safe_metrics}"
            )

    reclaim_fields = {
        "memory_reclaim_attempted": safe_report.get("memory_reclaim_attempted"),
        "memory_reclaim_supported": safe_report.get("memory_reclaim_supported"),
        "memory_reclaim_requested_kib": safe_report.get("memory_reclaim_requested_kib"),
        "memory_reclaim_raw_before_kib": safe_report.get("memory_reclaim_raw_before_kib"),
        "memory_reclaim_raw_after_kib": safe_report.get("memory_reclaim_raw_after_kib"),
        "memory_reclaim_working_set_before_kib": safe_report.get(
            "memory_reclaim_working_set_before_kib"
        ),
        "memory_reclaim_working_set_after_kib": safe_report.get(
            "memory_reclaim_working_set_after_kib"
        ),
        "memory_reclaim_delta_kib": safe_report.get("memory_reclaim_delta_kib"),
        "memory_reclaim_reclaimed_kib": safe_report.get(
            "memory_reclaim_reclaimed_kib"
        ),
        "memory_reclaim_effective": safe_report.get("memory_reclaim_effective"),
        "memory_reclaim_ever_effective": safe_report.get(
            "memory_reclaim_ever_effective"
        ),
        "memory_reclaim_error_type": safe_report.get("memory_reclaim_error_type"),
        "memory_reclaim_attempt_count": safe_report.get("memory_reclaim_attempt_count"),
        "memory_reclaim_success_count": safe_report.get("memory_reclaim_success_count"),
        "memory_reclaim_max_attempts": safe_report.get("memory_reclaim_max_attempts"),
    }
    detail = (
        f"stage_isolated_evidence_resource_boundary; stage={stage}; "
        f"trigger_reason={trigger}; "
        f"process_peak_rss_kib={safe_report.get('process_peak_rss_kib')}; "
        f"working_set_peak_kib={safe_report.get('container_peak_working_set_kib')}; "
        f"working_set_boundary_kib={safe_report.get('working_set_boundary_kib')}; "
        f"raw_peak_kib={safe_report.get('container_peak_memory_kib')}; "
        f"raw_hard_boundary_kib={safe_report.get('raw_hard_boundary_kib')}; "
        f"inactive_file_peak_kib={safe_report.get('container_peak_inactive_file_kib')}; "
        f"anon_peak_kib={safe_report.get('container_peak_anon_kib')}; "
        f"file_peak_kib={safe_report.get('container_peak_file_kib')}; "
        f"kernel_peak_kib={safe_report.get('container_peak_kernel_kib')}; "
        f"memory_accounting_source={safe_report.get('memory_accounting_source')}; "
        f"memory_reclaim_attempted={safe_report.get('memory_reclaim_attempted')}; "
        f"memory_reclaim_supported={safe_report.get('memory_reclaim_supported')}; "
        f"memory_reclaim_effective={safe_report.get('memory_reclaim_effective')}; "
        f"memory_reclaim_delta_kib={safe_report.get('memory_reclaim_delta_kib')}; "
        f"memory_reclaim_attempt_count={safe_report.get('memory_reclaim_attempt_count')}; "
        f"memory_reclaim_success_count={safe_report.get('memory_reclaim_success_count')}; "
        f"memory_reclaim_max_attempts={safe_report.get('memory_reclaim_max_attempts')}; "
        f"memory_reclaim_error_type={safe_report.get('memory_reclaim_error_type')}"
        f"{lane_detail}"
    )[:1600]
    print(
        json.dumps(
            {
                "event": _FAILURE_EVENT,
                "error_type": "ResourceBoundaryExceeded",
                "failure_stage": failure_stage,
                "error_detail": detail,
                "pipeline_id": pipeline_id,
                "memory_trigger_reason": trigger,
                "memory_process_peak_rss_kib": safe_report.get("process_peak_rss_kib"),
                "memory_working_set_peak_kib": safe_report.get(
                    "container_peak_working_set_kib"
                ),
                "memory_working_set_boundary_kib": safe_report.get(
                    "working_set_boundary_kib"
                ),
                "memory_raw_peak_kib": safe_report.get("container_peak_memory_kib"),
                "memory_raw_hard_boundary_kib": safe_report.get(
                    "raw_hard_boundary_kib"
                ),
                **reclaim_fields,
                **lane_fields,
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
