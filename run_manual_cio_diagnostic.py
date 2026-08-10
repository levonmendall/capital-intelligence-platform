"""Run one fully governed, paper-only CIO diagnostic outside the normal schedule.

The diagnostic bypasses only the calendar due check. It still requires fresh production
context, governed evidence, specialist review, CIO qualification, portfolio construction,
and every paper-execution control. It never authorizes real money.

Heavy application modules are intentionally imported only at the phase that needs them.
This keeps the release diagnostic's startup/canonical-state memory footprint bounded and
makes memory growth attributable to a governed phase rather than module import side effects.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


# These names remain module attributes so existing tests can monkeypatch them, while their
# implementations are loaded lazily at the governed phase that actually requires them.
ApiSettings = None
OperationalSettings = None
configure_logging = None
claim_manual_cio_diagnostic = None
finish_manual_cio_diagnostic = None
latest_manual_cio_diagnostic = None
record_manual_cio_diagnostic_progress = None
request_manual_cio_diagnostic = None
ensure_canonical_portfolio_store = None
prepare_production_context_for_cycle = None
invalidate_reuse_preserving_success = None
recording_context_preparer = None
collect_public_live_information_if_due = None
build_worker = None
paper_trading_launch_open = None
publish_pending_transaction_report = None
attempt_paper_execution = None
_payloads = None


_SECRET_ENVIRONMENT_NAMES = (
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "FRED_API_KEY",
    "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
    "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
    "OPENFIGI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "TWELVE_DATA_API_KEY",
    "TWELVE_API_KEY",
    "FINRA_API_CLIENT_ID",
    "FINRA_API_CLIENT_SECRET",
    "EIA_API_KEY",
    "NASA_FIRMS_MAP_KEY",
    "BEA_API_KEY",
    "CENSUS_API_KEY",
    "USDA_NASS_API_KEY",
)
_REDACTED = "[REDACTED]"


def _boolean(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _redact(value: str | None, values: Mapping[str, str]) -> str | None:
    if value is None:
        return None
    text = value
    secrets = {
        secret
        for name in _SECRET_ENVIRONMENT_NAMES
        if len(secret := values.get(name, "").strip()) >= 4
    }
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    text = re.sub(
        r"(?i)([?&](?:api[_-]?key|apikey|api_token|access_token|token)=)[^&\s]+",
        rf"\1{_REDACTED}",
        text,
    )
    text = re.sub(
        r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}",
        rf"\1{_REDACTED}",
        text,
    )
    return text[:2000]


def _log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-manual-cio-diagnostic",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "paper_only": True,
                "real_money_authorized": False,
                "secret_values_disclosed": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


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


def _cgroup_memory_kib() -> tuple[int | None, int | None]:
    current = _read_byte_counter(Path("/sys/fs/cgroup/memory.current"))
    limit = _read_byte_counter(Path("/sys/fs/cgroup/memory.max"))
    if current is not None and limit is not None and limit > 0:
        return current // 1024, limit // 1024
    current = _read_byte_counter(Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"))
    limit = _read_byte_counter(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))
    if current is not None and limit is not None and 0 < limit < (1 << 60):
        return current // 1024, limit // 1024
    return None, None


def _record_memory_phase(phase: str) -> None:
    """Emit lightweight process/container memory without importing application code."""

    rss_kib = _read_kib_field(Path("/proc/self/status"), "VmRSS")
    hwm_kib = _read_kib_field(Path("/proc/self/status"), "VmHWM")
    container_current_kib, container_limit_kib = _cgroup_memory_kib()
    _log(
        "manual_cio_diagnostic_memory_phase",
        phase=phase,
        pid=os.getpid(),
        rss_kib=rss_kib,
        hwm_kib=hwm_kib,
        container_current_kib=container_current_kib,
        container_limit_kib=container_limit_kib,
    )


def _load_coordination_dependencies() -> None:
    global ApiSettings, OperationalSettings, configure_logging
    global claim_manual_cio_diagnostic, finish_manual_cio_diagnostic
    global latest_manual_cio_diagnostic, record_manual_cio_diagnostic_progress
    global request_manual_cio_diagnostic

    if ApiSettings is None:
        from api.config import ApiSettings as implementation

        ApiSettings = implementation
    if OperationalSettings is None or configure_logging is None:
        from operations import OperationalSettings as settings_impl
        from operations import configure_logging as logging_impl

        OperationalSettings = settings_impl
        configure_logging = logging_impl
    if any(
        dependency is None
        for dependency in (
            claim_manual_cio_diagnostic,
            finish_manual_cio_diagnostic,
            latest_manual_cio_diagnostic,
            record_manual_cio_diagnostic_progress,
            request_manual_cio_diagnostic,
        )
    ):
        from operations.manual_cio_diagnostic import (
            claim_manual_cio_diagnostic as claim_impl,
            finish_manual_cio_diagnostic as finish_impl,
            latest_manual_cio_diagnostic as latest_impl,
            record_manual_cio_diagnostic_progress as progress_impl,
            request_manual_cio_diagnostic as request_impl,
        )

        claim_manual_cio_diagnostic = claim_impl
        finish_manual_cio_diagnostic = finish_impl
        latest_manual_cio_diagnostic = latest_impl
        record_manual_cio_diagnostic_progress = progress_impl
        request_manual_cio_diagnostic = request_impl


def _load_canonical_dependency() -> None:
    global ensure_canonical_portfolio_store
    if ensure_canonical_portfolio_store is None:
        from portfolio.state import ensure_canonical_portfolio_store as implementation

        ensure_canonical_portfolio_store = implementation


def _load_collection_dependency() -> None:
    global collect_public_live_information_if_due
    if collect_public_live_information_if_due is None:
        from public_live_collection_runtime import (
            collect_public_live_information_if_due as implementation,
        )

        collect_public_live_information_if_due = implementation


def _load_context_dependencies() -> None:
    global prepare_production_context_for_cycle
    global invalidate_reuse_preserving_success, recording_context_preparer

    if prepare_production_context_for_cycle is None:
        from production_context_publication_runtime import (
            prepare_production_context_for_cycle as implementation,
        )

        prepare_production_context_for_cycle = implementation
    if invalidate_reuse_preserving_success is None or recording_context_preparer is None:
        from production_context_state_resilience import (
            invalidate_reuse_preserving_success as invalidate_impl,
            recording_context_preparer as recording_impl,
        )

        invalidate_reuse_preserving_success = invalidate_impl
        recording_context_preparer = recording_impl


def _load_worker_dependency() -> None:
    global build_worker
    if build_worker is None:
        from run_scheduler import build_worker as implementation

        build_worker = implementation


def _load_execution_dependencies() -> None:
    global paper_trading_launch_open, publish_pending_transaction_report
    global attempt_paper_execution, _payloads

    if paper_trading_launch_open is None or publish_pending_transaction_report is None:
        from cio_pending_transactions import (
            paper_trading_launch_open as launch_impl,
            publish_pending_transaction_report as publish_impl,
        )

        paper_trading_launch_open = launch_impl
        publish_pending_transaction_report = publish_impl
    if attempt_paper_execution is None:
        from paper_execution_runtime import attempt_paper_execution as attempt_impl

        attempt_paper_execution = attempt_impl
    if _payloads is None:
        from run_autonomous_paper_operator import _payloads as payloads_impl

        _payloads = payloads_impl


def run_diagnostic_once(
    *,
    force: bool = False,
    values: Mapping[str, str] | None = None,
) -> int:
    resolved = os.environ if values is None else values
    _record_memory_phase("process_start")
    enabled = _boolean(
        resolved.get("CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE"),
        default=False,
    )
    release = _release(resolved)
    requester = f"render-release:{release}"
    if not enabled and not force:
        _log("manual_cio_diagnostic_disabled", release=release)
        return 0

    _load_coordination_dependencies()
    _record_memory_phase("after_coordination_imports")

    existing = latest_manual_cio_diagnostic(values=resolved)
    recovered_interrupted_request = False
    if existing is not None and existing.state == "in_progress":
        recovered_interrupted_request = True
        interrupted = finish_manual_cio_diagnostic(
            existing,
            succeeded=False,
            cycle_key=existing.cycle_key,
            snapshot_identifier=existing.snapshot_identifier,
            detail=(
                "Diagnostic execution was interrupted by a prior service process; "
                "the new service process may issue a replacement request."
            ),
            values=resolved,
        )
        _log(
            "manual_cio_diagnostic_interrupted_recovered",
            release=release,
            request_id=interrupted.request_id,
            prior_requester=interrupted.requested_by,
        )
        existing = interrupted

    if (
        not force
        and not recovered_interrupted_request
        and existing is not None
        and existing.requested_by == requester
        and existing.state in {"completed", "failed"}
    ):
        _log(
            "manual_cio_diagnostic_already_recorded",
            release=release,
            request_id=existing.request_id,
            state=existing.state,
            cycle_key=existing.cycle_key,
            snapshot_identifier=existing.snapshot_identifier,
        )
        return 0

    request, created = request_manual_cio_diagnostic(
        requested_by=requester,
        values=resolved,
    )
    if not created and request.requested_by != requester:
        _log(
            "manual_cio_diagnostic_request_busy",
            release=release,
            request_id=request.request_id,
            state=request.state,
        )
        return 0
    claimed = claim_manual_cio_diagnostic(values=resolved)
    if claimed is None:
        _log(
            "manual_cio_diagnostic_not_claimed",
            release=release,
            request_id=request.request_id,
            state=request.state,
        )
        return 0

    settings = ApiSettings.from_env(resolved)
    operational = OperationalSettings.from_env(resolved)
    configure_logging(operational)
    logger = logging.getLogger("capital_intelligence.manual_cio_diagnostic")

    cycle_key: str | None = None
    snapshot_identifier: str | None = None
    detail: str | None = None
    succeeded = False
    try:
        record_manual_cio_diagnostic_progress(
            "canonical_portfolio_initialization",
            values=resolved,
        )
        _record_memory_phase("before_canonical_portfolio_initialization")
        _load_canonical_dependency()
        ensure_canonical_portfolio_store(settings.portfolio_database)
        _record_memory_phase("after_canonical_portfolio_initialization")

        now = datetime.now(timezone.utc)
        record_manual_cio_diagnostic_progress(
            "public_information_collection",
            values=resolved,
        )
        _record_memory_phase("before_comprehensive_discovery")
        _load_collection_dependency()
        collect_public_live_information_if_due(now=now, force=True)
        _record_memory_phase("after_comprehensive_discovery")

        _load_context_dependencies()
        invalidate_reuse_preserving_success(settings)
        record_manual_cio_diagnostic_progress(
            "production_context_preparation",
            values=resolved,
        )
        _record_memory_phase("before_production_context_preparation")
        context_preparer = recording_context_preparer(
            prepare_production_context_for_cycle
        )
        context = context_preparer(settings=settings, scheduled_for=now)
        cycle_key = context.cycle_key
        _record_memory_phase("after_production_context_preparation")
        if not context.ready:
            detail = context.detail
        else:
            cycle_now = datetime.now(timezone.utc)
            record_manual_cio_diagnostic_progress(
                "six_specialist_committee_cio_cycle",
                values=resolved,
            )
            _record_memory_phase("before_worker_initialization")
            _load_worker_dependency()
            worker = build_worker(settings)
            _record_memory_phase("after_worker_initialization")
            result = worker.run_triggered(
                claimed.trigger_key,
                now=cycle_now,
                decision_as_of=context.decision_as_of,
            )
            worker.dispatch_pending()
            snapshot_identifier = result.snapshot_identifier
            detail = result.detail
            succeeded = result.status == "completed"
            if succeeded:
                record_manual_cio_diagnostic_progress(
                    "paper_implementation_boundary",
                    values=resolved,
                )
                _record_memory_phase("before_paper_implementation")
                _load_execution_dependencies()
                construction, briefing = _payloads(
                    settings,
                    expected_as_of=context.decision_as_of,
                )
                execution_now = datetime.now(timezone.utc)
                if paper_trading_launch_open(execution_now):
                    attempt = attempt_paper_execution(
                        construction=construction,
                        briefing=briefing,
                        now=execution_now,
                    )
                    publish_pending_transaction_report(
                        construction=construction,
                        briefing=briefing,
                        generated_at=execution_now,
                        execution_state=attempt.state,
                    )
                    detail = (
                        f"CIO diagnostic completed; paper_execution={attempt.state}."
                    )
                else:
                    detail = (
                        "CIO diagnostic completed; paper execution remains held by "
                        "the configured launch boundary."
                    )
                _record_memory_phase("after_paper_implementation")
    except Exception as error:  # Operational boundary; preserve fail-closed detail.
        detail = f"{type(error).__name__}: {error}"
        logger.error(
            "manual CIO diagnostic failed closed; error_type=%s",
            type(error).__name__,
        )
    finally:
        detail = _redact(detail, resolved)
        finished = finish_manual_cio_diagnostic(
            claimed,
            succeeded=succeeded,
            cycle_key=cycle_key,
            snapshot_identifier=snapshot_identifier,
            detail=detail,
            values=resolved,
        )

    _record_memory_phase("process_finish")
    _log(
        "manual_cio_diagnostic_completed" if succeeded else "manual_cio_diagnostic_failed",
        release=release,
        request_id=finished.request_id,
        state=finished.state,
        cycle_key=finished.cycle_key,
        snapshot_identifier=finished.snapshot_identifier,
        detail=finished.detail,
    )
    return 0 if succeeded else 3


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run another diagnostic even when this release already has a result.",
    )
    args = parser.parse_args(argv)
    try:
        return run_diagnostic_once(force=args.force)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        _log(
            "manual_cio_diagnostic_start_failed",
            error_type=type(error).__name__,
            detail=_redact(str(error), os.environ),
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
