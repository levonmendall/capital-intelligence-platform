"""Release clean data-root cache after each durable comprehensive lane on Render.

The comprehensive-discovery stage is serialized to one DAG worker on Render.  Once a lane
has durably qualified, this module launches a short-lived helper process that reuses the
bounded exact-owner cache scanner introduced for the pre-comprehensive boundary.  The
helper exits before the scheduler can submit the next serialized lane, so its own Python
working set cannot accumulate in the evidence-owner interpreter.

This is advisory operational hygiene only.  Timeout, launch failure, malformed telemetry,
or a nonzero helper exit cannot qualify evidence or change investment authority.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping


_EVENT = "comprehensive_discovery_lane_cache_reclamation"
_REPORT_SCHEMA = "pre-comprehensive-cache-reclamation.v1"
_TIMEOUT_SECONDS = 10.0
_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"
_CODE = """
import json
import os
from operations.pre_comprehensive_cache_reclamation import release_pre_comprehensive_completed_stage_file_cache
report = release_pre_comprehensive_completed_stage_file_cache(os.environ)
print(json.dumps(report, sort_keys=True))
""".strip()


def _enabled(values: Mapping[str, str]) -> bool:
    return (
        str(values.get("RENDER") or "").strip().lower() == "true"
        and str(values.get(_WORKERS_ENV) or "").strip() == "1"
    )


def _validated_report(raw: str | None) -> dict[str, object] | None:
    try:
        report = json.loads(str(raw or "").strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("schema_version") != _REPORT_SCHEMA:
        return None
    expected = {
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
    if any(report.get(key) is not value for key, value in expected.items()):
        return None
    return report


def run_post_lane_cache_reclamation(
    values: Mapping[str, str],
    *,
    node_id: str,
    asset_class: str,
) -> dict[str, object]:
    """Run one bounded fail-soft cache reclaimer after a durable lane checkpoint."""

    status = "skipped"
    return_code: int | None = None
    error_type: str | None = None
    report: dict[str, object] | None = None

    if _enabled(values):
        status = "completed"
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
        except subprocess.TimeoutExpired:
            status = "timed_out"
            error_type = "CacheReclamationTimeout"
        except OSError:
            status = "unavailable"
            error_type = "CacheReclamationLaunchError"

    payload: dict[str, object] = {
        "event": _EVENT,
        "node_id": str(node_id)[:160],
        "asset_class": str(asset_class)[:96],
        "status": status,
        "return_code": return_code,
        "error_type": error_type,
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


__all__ = ["run_post_lane_cache_reclamation"]
