"""Release clean data-root cache around comprehensive-discovery lane handoffs on Render.

The comprehensive-discovery stage is serialized to one DAG worker on Render. Immediately
after a successful lane process exits, the lightweight parent can reclaim the exact
current-release comprehensive spool synchronously before durable success bookkeeping or
the next lane launch. After the success checkpoint is durable, this module repeats that
narrow pass and launches the existing short-lived broad data-root helper as a fail-soft
fallback.

All reclamation is advisory operational hygiene only. Failure, timeout, malformed
telemetry, or cache-advice failure cannot qualify evidence or change investment authority.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping


_EVENT = "comprehensive_discovery_lane_cache_reclamation"
_EXIT_EVENT = "comprehensive_discovery_lane_exit_cache_reclamation"
_REPORT_SCHEMA = "pre-comprehensive-cache-reclamation.v1"
_TIMEOUT_SECONDS = 10.0
_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"
_EXACT_SCAN_MAX_ENTRIES_ENV = "CAPITAL_INTELLIGENCE_POST_LANE_SPOOL_SCAN_MAX_ENTRIES"
_DEFAULT_EXACT_SCAN_MAX_ENTRIES = 12_000
_SAFE_RELEASE = re.compile(r"[^A-Za-z0-9_.-]+")
_TRANSIENT_SUFFIXES = (".lock", ".part", ".partial", ".tmp")
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


def _bounded_int(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(str(values.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _safe_release(value: str) -> str:
    normalized = _SAFE_RELEASE.sub("-", str(value or "").strip()).strip("-.")
    return normalized or "unknown"


def _release(values: Mapping[str, str]) -> str:
    return (
        str(values.get("CAPITAL_INTELLIGENCE_RELEASE") or "").strip()
        or str(values.get("RENDER_GIT_COMMIT") or "").strip()
        or str(values.get("GITHUB_SHA") or "").strip()
        or "unknown"
    )


def _current_release_spool_root(values: Mapping[str, str]) -> Path | None:
    data_root = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    release = _release(values)
    if not data_root or not release or release == "unknown":
        return None
    return (
        Path(data_root).expanduser()
        / "comprehensive-discovery-spool"
        / _safe_release(release)
    )


def _memory_snapshot() -> dict[str, int | None]:
    root = Path("/sys/fs/cgroup")
    snapshot: dict[str, int | None] = {
        "raw_current_kib": None,
        "inactive_file_kib": None,
    }
    try:
        snapshot["raw_current_kib"] = int(
            (root / "memory.current").read_text(encoding="utf-8").strip()
        ) // 1024
    except (OSError, ValueError):
        pass

    try:
        lines = (root / "memory.stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return snapshot
    for line in lines:
        name, _, raw_value = line.partition(" ")
        if name != "inactive_file":
            continue
        try:
            snapshot["inactive_file_kib"] = int(raw_value.strip()) // 1024
        except ValueError:
            pass
        break
    return snapshot


def _reclaimed_kib(
    before: Mapping[str, int | None],
    after: Mapping[str, int | None],
    key: str,
) -> int | None:
    before_value = before.get(key)
    after_value = after.get(key)
    if not isinstance(before_value, int) or not isinstance(after_value, int):
        return None
    return max(0, before_value - after_value)


def _advise_clean_file_cache_dontneed(path: Path) -> bool:
    """Flush one durable spool file, then advise its clean pages reclaimable."""

    posix_fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    fsync = getattr(os, "fsync", None)
    if posix_fadvise is None or advice is None or not callable(fsync):
        return False
    try:
        if path.is_symlink() or not path.is_file():
            return False
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            fsync(descriptor)
            posix_fadvise(descriptor, 0, 0, advice)
        except (OSError, TypeError, ValueError):
            return False
        return True
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _release_current_release_spool_file_cache(
    values: Mapping[str, str],
) -> dict[str, object]:
    """Stream exact-release spool files through cache advice without touching evidence."""

    root = _current_release_spool_root(values)
    scan_max_entries = _bounded_int(
        values,
        _EXACT_SCAN_MAX_ENTRIES_ENV,
        _DEFAULT_EXACT_SCAN_MAX_ENTRIES,
        minimum=1_000,
        maximum=50_000,
    )
    before = _memory_snapshot()
    scanned_entries = 0
    candidate_file_count = 0
    candidate_bytes = 0
    released_file_count = 0
    released_bytes = 0
    scan_truncated = False

    directories: list[Path] = []
    if root is not None and root.is_dir():
        directories.append(root)

    while directories and not scan_truncated:
        directory = directories.pop()
        try:
            iterator = os.scandir(directory)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                scanned_entries += 1
                if scanned_entries > scan_max_entries:
                    scan_truncated = True
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if entry.name.lower().endswith(_TRANSIENT_SUFFIXES):
                        continue
                    size = int(entry.stat(follow_symlinks=False).st_size)
                except OSError:
                    continue

                path = Path(entry.path)
                candidate_file_count += 1
                candidate_bytes += size
                if _advise_clean_file_cache_dontneed(path):
                    released_file_count += 1
                    released_bytes += size

    after = _memory_snapshot()
    return {
        "root_configured": root is not None,
        "scan_entries": scanned_entries,
        "scan_max_entries": scan_max_entries,
        "scan_truncated": scan_truncated,
        "candidate_file_count": candidate_file_count,
        "candidate_bytes": candidate_bytes,
        "released_file_count": released_file_count,
        "released_bytes": released_bytes,
        "raw_current_reclaimed_kib": _reclaimed_kib(before, after, "raw_current_kib"),
        "inactive_file_reclaimed_kib": _reclaimed_kib(
            before, after, "inactive_file_kib"
        ),
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


def run_lane_exit_exact_spool_cache_reclamation(
    values: Mapping[str, str],
    *,
    node_id: str,
    asset_class: str,
) -> dict[str, object]:
    """Reclaim exact spool cache immediately after a successful lane child exits.

    This intentionally does not launch the broad helper. The purpose of this boundary is
    to begin useful cache advice before success persistence/progress publication and before
    another serialized lane can be launched. It is strictly advisory and fail-soft.
    """

    status = "skipped"
    error_type: str | None = None
    report: dict[str, object] | None = None
    if _enabled(values):
        try:
            report = _release_current_release_spool_file_cache(values)
            status = "completed"
        except Exception:  # noqa: BLE001 - cache hygiene remains advisory.
            status = "failed"
            error_type = "ExactSpoolCacheReclamationError"

    payload: dict[str, object] = {
        "event": _EXIT_EVENT,
        "node_id": str(node_id)[:160],
        "asset_class": str(asset_class)[:96],
        "status": status,
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
        payload["exact_release_spool"] = report
        for source, target in (
            ("candidate_file_count", "exact_spool_candidate_file_count"),
            ("candidate_bytes", "exact_spool_candidate_bytes"),
            ("released_file_count", "exact_spool_released_file_count"),
            ("released_bytes", "exact_spool_released_bytes"),
            ("scan_truncated", "exact_spool_scan_truncated"),
            ("raw_current_reclaimed_kib", "exact_spool_raw_current_reclaimed_kib"),
            (
                "inactive_file_reclaimed_kib",
                "exact_spool_inactive_file_reclaimed_kib",
            ),
        ):
            payload[target] = report.get(source)
    print(json.dumps(payload, sort_keys=True), flush=True)
    return payload


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
    """Repeat exact spool release, then one bounded fail-soft broad reclaimer."""

    status = "skipped"
    return_code: int | None = None
    error_type: str | None = None
    report: dict[str, object] | None = None
    exact_spool: dict[str, object] | None = None

    if _enabled(values):
        try:
            exact_spool = _release_current_release_spool_file_cache(values)
        except Exception:  # noqa: BLE001 - cache hygiene remains strictly advisory.
            exact_spool = {
                "status": "failed",
                "error_type": "ExactSpoolCacheReclamationError",
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
    if exact_spool is not None:
        payload["exact_release_spool"] = exact_spool
        for source, target in (
            ("candidate_file_count", "exact_spool_candidate_file_count"),
            ("candidate_bytes", "exact_spool_candidate_bytes"),
            ("released_file_count", "exact_spool_released_file_count"),
            ("released_bytes", "exact_spool_released_bytes"),
            ("scan_truncated", "exact_spool_scan_truncated"),
            ("raw_current_reclaimed_kib", "exact_spool_raw_current_reclaimed_kib"),
            (
                "inactive_file_reclaimed_kib",
                "exact_spool_inactive_file_reclaimed_kib",
            ),
        ):
            payload[target] = exact_spool.get(source)
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


__all__ = [
    "run_lane_exit_exact_spool_cache_reclamation",
    "run_post_lane_cache_reclamation",
]
