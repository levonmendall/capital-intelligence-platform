"""Reclaim completed publication-lane clean cache in a disposable bounded child.

Production telemetry after the in-process publication reclaimer showed the opposite memory
shape from the preceding failure: file cache fell materially, but cgroup anonymous memory
rose sharply and the long-lived comprehensive parent failed after fewer lanes. The broad
reclaimer allocates a bounded scan/manifest working set that should not survive the lane
handoff merely because Python's allocator keeps heap pages attached to the parent.

This module therefore keeps the publication boundary introduced for comprehensive discovery
but executes the broad data-root scan in a fresh short-lived interpreter after the completed
lane child has exited and its durable transaction state has been validated. The coordinator
already performs the exact-spool release first, so useful file-cache advice begins before
this child is launched. When this child exits, all of its anonymous heap is returned to the
OS before another serialized publication lane can begin.

Publication transactions are intrinsically serial at this call site, so this wrapper does
not depend on the later provider-facing DAG worker override. The returned ownership report
is accepted only when the established non-authoritative contract is intact. Reclamation is
bounded, advisory, and fail-soft and cannot certify evidence or alter resource limits,
providers, market scope, CIO authority, construction, execution, or paper-only controls.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path


_EVENT = "comprehensive_discovery_publication_lane_cache_reclamation"
_REPORT_SCHEMA = "pre-comprehensive-cache-reclamation.v1"
_TIMEOUT_SECONDS = 10.0
_CODE = """
import json
import os
from operations.pre_comprehensive_cache_reclamation import release_pre_comprehensive_completed_stage_file_cache
report = release_pre_comprehensive_completed_stage_file_cache(os.environ)
print(json.dumps(report, sort_keys=True))
""".strip()

_AUTHORITY_CONTRACT = {
    "advisory_only": True,
    "evidence_certified": False,
    "decision_authority": False,
    "candidate_authority": False,
    "sizing_authority": False,
    "construction_authority": False,
    "execution_authority": False,
    "paper_only": True,
    "real_money_authorized": False,
    "credential_safe": True,
}


def _enabled(values: Mapping[str, str]) -> bool:
    # This wrapper is called only by the transactional publication coordinator, whose lane
    # loop is strictly serial independent of the later provider-facing DAG worker count.
    # Requiring that later scheduler override here can silently skip the exact boundary we
    # need to protect. Keep only the production-platform guard.
    return str(values.get("RENDER") or "").strip().lower() == "true"


def _validated_report(raw: str | None) -> dict[str, object] | None:
    try:
        report = json.loads(str(raw or "").strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("schema_version") != _REPORT_SCHEMA:
        return None
    if any(report.get(key) is not value for key, value in _AUTHORITY_CONTRACT.items()):
        return None
    return report


def run_publication_lane_cache_reclamation(
    values: Mapping[str, str],
    *,
    asset_class: str,
    index: int,
) -> dict[str, object]:
    """Run one bounded broad clean-cache pass in a disposable interpreter."""

    status = "skipped"
    return_code: int | None = None
    error_type: str | None = None
    report: dict[str, object] | None = None

    if _enabled(values):
        try:
            completed = subprocess.run(
                (sys.executable, "-c", _CODE),
                env=dict(values),
                cwd=str(Path(__file__).resolve().parents[1]),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
                start_new_session=False,
            )
            return_code = int(completed.returncode)
            if return_code != 0:
                status = "failed"
                error_type = "CacheReclamationProcessError"
            else:
                report = _validated_report(completed.stdout)
                if report is None:
                    status = "invalid_report"
                    error_type = "CacheReclamationReportError"
                else:
                    status = "completed"
        except subprocess.TimeoutExpired:
            status = "timed_out"
            error_type = "CacheReclamationTimeout"
        except OSError:
            status = "unavailable"
            error_type = "CacheReclamationLaunchError"

    payload: dict[str, object] = {
        "event": _EVENT,
        "asset_class": str(asset_class)[:96],
        "lane_index": int(index),
        "status": status,
        "return_code": return_code,
        "disposable_child": True,
        "error_type": error_type,
        **_AUTHORITY_CONTRACT,
    }
    if report is not None:
        payload["cache_ownership"] = report
        for key in (
            "candidate_file_count",
            "candidate_bytes",
            "selected_file_count",
            "selected_bytes",
            "released_file_count",
            "released_bytes",
            "scan_truncated",
            "manifest_truncated",
            "raw_current_reclaimed_kib",
            "inactive_file_reclaimed_kib",
        ):
            payload[key] = report.get(key)

    print(json.dumps(payload, sort_keys=True), flush=True)
    return payload


__all__ = ["run_publication_lane_cache_reclamation"]
