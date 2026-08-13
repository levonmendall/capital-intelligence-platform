"""Durable, paper-only requests for an administrator-triggered CIO diagnostic cycle.

The request file is operational coordination state. It cannot authorize candidates,
portfolio changes, paper execution, or real money. The autonomous paper operator claims
at most one pending request and then runs the existing fully governed context, specialist,
CIO, construction, and paper-execution path with a unique material-event cycle key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


_SCHEMA_VERSION = "manual-cio-diagnostic.v1"
_ACTIVE_STATES = frozenset({"pending", "in_progress"})
_FINAL_STATES = frozenset({"completed", "failed"})
_PROGRESS_ENABLED = "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED"
_CONTEXT_STATE_FILENAME = "production-context-publication-state.json"
_DEFAULT_MEMORY_HIGH_WATER_FRACTION = 0.70
_DEFAULT_MEMORY_RESERVE_MB = 640.0
_RENDER_MEMORY_LIMIT_FALLBACK_MB = 2048.0
_PROGRESS_STAGE_ALIASES = {
    "catalog_databento_options": "catalog_options",
    "catalog_databento_options_complete": "catalog_options_complete",
}
_PROGRESS_STAGES = frozenset(
    {
        "canonical_portfolio_initialization",
        "public_information_collection",
        "production_context_preparation",
        "six_specialist_committee_cio_cycle",
        "paper_implementation_boundary",
        "comprehensive_catalog_discovery",
        "catalog_eodhd_directories",
        "catalog_eodhd_directories_complete",
        "catalog_options",
        "catalog_options_partitioned",
        "catalog_options_expiration_partition",
        "catalog_options_partitioned_complete",
        "catalog_options_complete",
        "comprehensive_catalog_discovery_complete",
        "certified_catalog_merge_complete",
        "provider_preselection_publication",
        "provider_preselection_bulk_snapshots",
        "provider_preselection_bulk_snapshots_complete",
        "provider_preselection_fallback_probe",
        "provider_preselection_fallback_probe_complete",
        "provider_preselection_publication_complete",
        "comprehensive_market_discovery_complete",
    }
)
_PROGRESS_LANE_STAGES = frozenset(
    {
        "terminal_screening",
        "terminal_screening_chunk",
        "terminal_screening_finalize_release",
        "terminal_screening_finalize_diversification",
        "terminal_screening_finalize_rankings",
        "terminal_screening_finalize_selection",
        "terminal_screening_finalize_plan",
        "deep_market_evidence",
        "deep_market_evidence_complete",
        "terminal_accounting_complete",
    }
)
_PROGRESS_LANES = frozenset(
    {
        "us_equity",
        "us_etf",
        "cash_equivalent",
        "fixed_income",
        "international_equity",
        "commodity",
        "fx",
        "crypto",
        "real_estate",
        "future",
        "option",
        "volatility",
        "alternative",
        "other",
    }
)
_PROGRESS_METRICS = frozenset(
    {
        "configured_exchanges",
        "configured_underlyings",
        "catalog_records",
        "continuity_records",
        "decision_eligible_records",
        "evidence_complete_records",
        "excluded",
        "selected",
        "scheduled_lanes",
        "processed_records",
        "total_records",
        "chunk_records",
        "rss_kib",
        "hwm_kib",
        "service_rss_kib",
        "container_current_kib",
        "container_limit_kib",
        "container_anon_kib",
        "container_file_kib",
        "container_shmem_kib",
        "container_kernel_kib",
        "memory_reserve_kib",
        "governed_boundary_kib",
        "governed_headroom_kib",
        "publication_bytes",
        "publication_index_bytes",
        "screening_spool_bytes",
        "chunk_file_bytes",
        "storage_reserve_bytes",
        "storage_total_bytes",
        "storage_used_bytes",
        "storage_free_bytes",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("diagnostic timestamps must be non-empty strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _aware(parsed, field_name="diagnostic timestamp")


def _normalize_progress_metrics(
    metrics: Mapping[str, object] | None,
) -> tuple[tuple[str, int], ...]:
    normalized: list[tuple[str, int]] = []
    for raw_name, raw_value in sorted((metrics or {}).items()):
        name = str(raw_name).strip().lower()
        if name not in _PROGRESS_METRICS:
            raise ValueError("manual CIO diagnostic progress metric name is invalid")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
            raise ValueError(
                "manual CIO diagnostic progress metrics must be nonnegative integers"
            )
        normalized.append((name, raw_value))
    return tuple(normalized)


def _read_kib_field(path: Path, field: str) -> int | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    prefix = field + ":"
    for line in content.splitlines():
        if not line.startswith(prefix):
            continue
        parts = line[len(prefix) :].strip().split()
        if not parts:
            return None
        try:
            return int(parts[0])
        except ValueError:
            return None
    return None


def _read_byte_counter(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_keyed_byte_counters(path: Path) -> dict[str, int]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    counters: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            value = int(parts[1])
        except ValueError:
            continue
        if value >= 0:
            counters[parts[0]] = value
    return counters


def _cgroup_memory_kib() -> tuple[int | None, int | None]:
    v2_current = _read_byte_counter(Path("/sys/fs/cgroup/memory.current"))
    v2_limit = _read_byte_counter(Path("/sys/fs/cgroup/memory.max"))
    if v2_current is not None and v2_limit is not None and v2_limit > 0:
        return v2_current // 1024, v2_limit // 1024

    v1_current = _read_byte_counter(
        Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    )
    v1_limit = _read_byte_counter(
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    )
    if v1_current is not None and v1_limit is not None and 0 < v1_limit < (1 << 60):
        return v1_current // 1024, v1_limit // 1024
    return None, None


def _cgroup_memory_stat_kib() -> dict[str, int]:
    counters = _read_keyed_byte_counters(Path("/sys/fs/cgroup/memory.stat"))
    if not counters:
        counters = _read_keyed_byte_counters(
            Path("/sys/fs/cgroup/memory/memory.stat")
        )
    result: dict[str, int] = {}
    for source, metric in (
        ("anon", "container_anon_kib"),
        ("file", "container_file_kib"),
        ("shmem", "container_shmem_kib"),
        ("kernel", "container_kernel_kib"),
    ):
        value = counters.get(source)
        if value is not None and value >= 0:
            result[metric] = value // 1024
    return result


def _proc_total_rss_kib() -> int | None:
    total = 0
    observed = False
    try:
        entries = tuple(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        rss = _read_kib_field(entry / "status", "VmRSS")
        if rss is None:
            continue
        observed = True
        total += rss
    return total if observed else None


def _configured_memory_limit_kib(values: Mapping[str, str]) -> int | None:
    raw = values.get("CAPITAL_INTELLIGENCE_CONTAINER_MEMORY_LIMIT_MB", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return None
        if value <= 0:
            return None
        return int(value * 1024)
    if values.get("RENDER", "").strip().lower() == "true":
        return int(_RENDER_MEMORY_LIMIT_FALLBACK_MB * 1024)
    return None


def _container_memory_kib(
    values: Mapping[str, str],
) -> tuple[int | None, int | None]:
    current, limit = _cgroup_memory_kib()
    if current is not None and limit is not None:
        return current, limit
    configured_limit = _configured_memory_limit_kib(values)
    if configured_limit is None:
        return None, None
    return _proc_total_rss_kib(), configured_limit


def _configured_memory_reserve_kib(values: Mapping[str, str]) -> int | None:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_RESERVE_MB", ""
    ).strip()
    if not raw:
        value = _DEFAULT_MEMORY_RESERVE_MB
    else:
        try:
            value = float(raw)
        except ValueError:
            return None
    if value < 256.0:
        return None
    return int(value * 1024)


def _configured_memory_high_water_fraction(
    values: Mapping[str, str],
) -> float | None:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION", ""
    ).strip()
    if not raw:
        return _DEFAULT_MEMORY_HIGH_WATER_FRACTION
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0.5 <= value < 0.9 else None


def _terminal_screening_resource_metrics(
    values: Mapping[str, str],
) -> dict[str, int]:
    """Return best-effort credential-safe process and cgroup memory counters."""
    metrics: dict[str, int] = {}
    status = Path(f"/proc/{os.getpid()}/status")
    rss_kib = _read_kib_field(status, "VmRSS")
    hwm_kib = _read_kib_field(status, "VmHWM")
    if rss_kib is not None and rss_kib >= 0:
        metrics["rss_kib"] = rss_kib
    if hwm_kib is not None and hwm_kib >= 0:
        metrics["hwm_kib"] = hwm_kib

    service_rss_kib = _proc_total_rss_kib()
    if service_rss_kib is not None and service_rss_kib >= 0:
        metrics["service_rss_kib"] = service_rss_kib
    metrics.update(_cgroup_memory_stat_kib())

    current_kib, limit_kib = _container_memory_kib(values)
    if current_kib is not None and current_kib >= 0:
        metrics["container_current_kib"] = current_kib
    if limit_kib is not None and limit_kib > 0:
        metrics["container_limit_kib"] = limit_kib

    reserve_kib = _configured_memory_reserve_kib(values)
    high_water_fraction = _configured_memory_high_water_fraction(values)
    if reserve_kib is not None:
        metrics["memory_reserve_kib"] = reserve_kib
    if (
        limit_kib is not None
        and limit_kib > 0
        and reserve_kib is not None
        and high_water_fraction is not None
    ):
        fractional = int(limit_kib * high_water_fraction)
        reserve_based = limit_kib - reserve_kib
        if reserve_based <= 0:
            reserve_based = int(limit_kib * 0.5)
        boundary_kib = max(1, min(fractional, reserve_based))
        metrics["governed_boundary_kib"] = boundary_kib
        if current_kib is not None:
            metrics["governed_headroom_kib"] = max(0, boundary_kib - current_kib)
    return metrics


@dataclass(frozen=True, slots=True)
class ManualCIODiagnosticRequest:
    request_id: str
    requested_at: datetime
    requested_by: str
    state: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cycle_key: str | None = None
    snapshot_identifier: str | None = None
    detail: str | None = None
    progress_stage: str | None = None
    progress_metrics: tuple[tuple[str, int], ...] = ()
    progress_recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id cannot be empty")
        if not self.requested_by.strip():
            raise ValueError("requested_by cannot be empty")
        _aware(self.requested_at, field_name="requested_at")
        if self.started_at is not None:
            _aware(self.started_at, field_name="started_at")
        if self.completed_at is not None:
            _aware(self.completed_at, field_name="completed_at")
        if self.progress_recorded_at is not None:
            _aware(self.progress_recorded_at, field_name="progress_recorded_at")
        if self.state not in _ACTIVE_STATES | _FINAL_STATES:
            raise ValueError("unsupported manual diagnostic state")
        if self.state == "in_progress" and self.started_at is None:
            raise ValueError("in-progress diagnostics require started_at")
        if self.state in _FINAL_STATES and self.completed_at is None:
            raise ValueError("final diagnostics require completed_at")
        if self.progress_stage is not None and not self.progress_stage.strip():
            raise ValueError("progress_stage cannot be empty")
        if _normalize_progress_metrics(dict(self.progress_metrics)) != self.progress_metrics:
            raise ValueError("progress_metrics must be normalized and unique")

    @property
    def trigger_key(self) -> str:
        return f"manual-diagnostic-{self.request_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "request_id": self.request_id,
            "requested_at": self.requested_at.astimezone(timezone.utc).isoformat(),
            "requested_by": self.requested_by,
            "state": self.state,
            "started_at": None
            if self.started_at is None
            else self.started_at.astimezone(timezone.utc).isoformat(),
            "completed_at": None
            if self.completed_at is None
            else self.completed_at.astimezone(timezone.utc).isoformat(),
            "cycle_key": self.cycle_key,
            "snapshot_identifier": self.snapshot_identifier,
            "detail": self.detail,
            "progress_stage": self.progress_stage,
            "progress_metrics": dict(self.progress_metrics),
            "progress_recorded_at": None
            if self.progress_recorded_at is None
            else self.progress_recorded_at.astimezone(timezone.utc).isoformat(),
            "paper_only": True,
            "real_money_authorized": False,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ManualCIODiagnosticRequest":
        if payload.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported manual CIO diagnostic schema")
        raw_progress_metrics = payload.get("progress_metrics")
        if raw_progress_metrics is None:
            progress_metrics: tuple[tuple[str, int], ...] = ()
        elif isinstance(raw_progress_metrics, Mapping):
            progress_metrics = _normalize_progress_metrics(raw_progress_metrics)
        else:
            raise ValueError(
                "manual CIO diagnostic progress_metrics must be an object"
            )
        requested_at = _optional_datetime(payload.get("requested_at"))
        if requested_at is None:
            raise ValueError("requested_at is required")
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            requested_at=requested_at,
            requested_by=str(payload.get("requested_by") or "").strip(),
            state=str(payload.get("state") or "").strip(),
            started_at=_optional_datetime(payload.get("started_at")),
            completed_at=_optional_datetime(payload.get("completed_at")),
            cycle_key=None
            if payload.get("cycle_key") is None
            else str(payload.get("cycle_key")).strip() or None,
            snapshot_identifier=None
            if payload.get("snapshot_identifier") is None
            else str(payload.get("snapshot_identifier")).strip() or None,
            detail=None
            if payload.get("detail") is None
            else str(payload.get("detail"))[:2000],
            progress_stage=None
            if payload.get("progress_stage") is None
            else str(payload.get("progress_stage")).strip() or None,
            progress_metrics=progress_metrics,
            progress_recorded_at=_optional_datetime(
                payload.get("progress_recorded_at")
            ),
        )


def diagnostic_request_path(values: Mapping[str, str] | None = None) -> Path:
    resolved = os.environ if values is None else values
    configured = resolved.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH", ""
    ).strip()
    if configured:
        return Path(configured).expanduser()
    data_root = Path(
        resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return data_root / "manual-cio-diagnostic.json"


def _read(path: Path) -> ManualCIODiagnosticRequest | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"manual CIO diagnostic state is invalid: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("manual CIO diagnostic state must be an object")
    return ManualCIODiagnosticRequest.from_dict(payload)


def _write(path: Path, request: ManualCIODiagnosticRequest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _published_context_cycle(path: Path) -> str | None:
    context_path = path.parent / _CONTEXT_STATE_FILENAME
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    cycle_key = str(payload.get("cycle_key") or "").strip()
    if not cycle_key or cycle_key.startswith("refresh-required:"):
        return None
    return cycle_key


def latest_manual_cio_diagnostic(
    *, values: Mapping[str, str] | None = None
) -> ManualCIODiagnosticRequest | None:
    return _read(diagnostic_request_path(values))


def record_manual_cio_diagnostic_progress(
    stage: str,
    *,
    metrics: Mapping[str, int] | None = None,
    values: Mapping[str, str] | None = None,
) -> ManualCIODiagnosticRequest | None:
    """Persist credential-safe progress for the active release diagnostic only."""
    resolved = os.environ if values is None else values
    enabled = resolved.get(_PROGRESS_ENABLED, "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    normalized_stage = str(stage).strip().lower()
    normalized_stage = _PROGRESS_STAGE_ALIASES.get(
        normalized_stage, normalized_stage
    )
    lane_stage = normalized_stage.split(":", 1)
    if normalized_stage not in _PROGRESS_STAGES and not (
        len(lane_stage) == 2
        and lane_stage[0] in _PROGRESS_LANE_STAGES
        and lane_stage[1] in _PROGRESS_LANES
    ):
        raise ValueError("manual CIO diagnostic progress stage is invalid")

    explicit_metrics = _normalize_progress_metrics(metrics)
    combined_metrics: dict[str, object] = dict(metrics or {})
    # Production uses the process environment (values=None). Capture the same safe
    # resource attribution at every production phase, including catalog/options and
    # provider preparation. Explicit test/config mappings retain the legacy behavior
    # except for terminal/finalization stages, which remain directly testable.
    collect_resources = values is None or lane_stage[0].startswith(
        "terminal_screening"
    )
    if collect_resources:
        for name, value in _terminal_screening_resource_metrics(resolved).items():
            combined_metrics.setdefault(name, value)
    normalized_metrics = _normalize_progress_metrics(combined_metrics)

    path = diagnostic_request_path(resolved)
    existing = _read(path)
    if existing is None or existing.state != "in_progress":
        return None
    message = f"governed_progress={normalized_stage}"
    if explicit_metrics:
        message += "; " + "; ".join(
            f"{name}={value}" for name, value in explicit_metrics
        )

    cycle_key = existing.cycle_key
    if cycle_key is None and normalized_stage == "six_specialist_committee_cio_cycle":
        cycle_key = _published_context_cycle(path)

    updated = replace(
        existing,
        detail=message,
        progress_stage=normalized_stage,
        progress_metrics=normalized_metrics,
        progress_recorded_at=_utc_now(),
        cycle_key=cycle_key,
    )
    _write(path, updated)
    return updated


def request_manual_cio_diagnostic(
    *,
    requested_by: str,
    now: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> tuple[ManualCIODiagnosticRequest, bool]:
    requester = requested_by.strip()
    if not requester:
        raise ValueError("requested_by cannot be empty")
    path = diagnostic_request_path(values)
    existing = _read(path)
    if existing is not None and existing.state in _ACTIVE_STATES:
        return existing, False
    requested_at = _aware(now or _utc_now(), field_name="now")
    request = ManualCIODiagnosticRequest(
        request_id=uuid4().hex,
        requested_at=requested_at,
        requested_by=requester,
    )
    _write(path, request)
    return request, True


def claim_manual_cio_diagnostic(
    *,
    now: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> ManualCIODiagnosticRequest | None:
    path = diagnostic_request_path(values)
    request = _read(path)
    if request is None or request.state != "pending":
        return None
    claimed = replace(
        request,
        state="in_progress",
        started_at=_aware(now or _utc_now(), field_name="now"),
        detail="The autonomous paper operator claimed the diagnostic request.",
    )
    _write(path, claimed)
    return claimed


def finish_manual_cio_diagnostic(
    request: ManualCIODiagnosticRequest,
    *,
    succeeded: bool,
    cycle_key: str | None,
    snapshot_identifier: str | None,
    detail: str | None,
    now: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> ManualCIODiagnosticRequest:
    if request.state != "in_progress":
        raise ValueError("only an in-progress diagnostic can be finished")
    path = diagnostic_request_path(values)
    latest = _read(path)
    if (
        latest is None
        or latest.request_id != request.request_id
        or latest.state != "in_progress"
    ):
        raise ValueError(
            "diagnostic finalization requires the current in-progress request"
        )
    if latest.cycle_key and cycle_key and latest.cycle_key != cycle_key:
        raise ValueError("diagnostic context cycle cannot be rebound during finalization")
    finished = replace(
        latest,
        state="completed" if succeeded else "failed",
        completed_at=_aware(now or _utc_now(), field_name="now"),
        cycle_key=cycle_key or latest.cycle_key,
        snapshot_identifier=snapshot_identifier or latest.snapshot_identifier,
        detail=None if detail is None else detail[:2000],
    )
    _write(path, finished)
    return finished


__all__ = [
    "ManualCIODiagnosticRequest",
    "claim_manual_cio_diagnostic",
    "diagnostic_request_path",
    "finish_manual_cio_diagnostic",
    "latest_manual_cio_diagnostic",
    "record_manual_cio_diagnostic_progress",
    "request_manual_cio_diagnostic",
]
