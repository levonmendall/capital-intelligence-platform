"""Run one fully governed, paper-only CIO diagnostic outside the normal schedule.

The diagnostic bypasses only the calendar due check. It still requires fresh production
context, governed evidence, specialist review, CIO qualification, portfolio construction,
and every paper-execution control. It never authorizes real money.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Mapping, Sequence

from api.config import ApiSettings
from cio_pending_transactions import (
    paper_trading_launch_open,
    publish_pending_transaction_report,
)
from operations import OperationalSettings, configure_logging
from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)
from paper_execution_runtime import attempt_paper_execution
from portfolio.state import ensure_canonical_portfolio_store
from production_context_publication_runtime import prepare_production_context_for_cycle
from production_context_state_resilience import (
    invalidate_reuse_preserving_success,
    recording_context_preparer,
)
from public_live_collection_runtime import collect_public_live_information_if_due
from run_autonomous_paper_operator import _payloads
from run_scheduler import build_worker


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


def run_diagnostic_once(
    *,
    force: bool = False,
    values: Mapping[str, str] | None = None,
) -> int:
    resolved = os.environ if values is None else values
    enabled = _boolean(
        resolved.get("CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE"),
        default=False,
    )
    release = _release(resolved)
    requester = f"render-release:{release}"
    if not enabled and not force:
        _log("manual_cio_diagnostic_disabled", release=release)
        return 0

    existing = latest_manual_cio_diagnostic(values=resolved)
    # An in-progress record observed during a fresh process startup belongs to a
    # process that did not survive the preceding restart/deploy. Close it truthfully
    # before requesting the current release's diagnostic so troubleshooting cannot
    # become permanently wedged on durable coordination state.
    if existing is not None and existing.state == "in_progress":
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
        ensure_canonical_portfolio_store(settings.portfolio_database)
        worker = build_worker(settings)
        context_preparer = recording_context_preparer(
            prepare_production_context_for_cycle
        )
        now = datetime.now(timezone.utc)
        collect_public_live_information_if_due(now=now, force=True)
        invalidate_reuse_preserving_success(settings)
        context = context_preparer(settings=settings, scheduled_for=now)
        cycle_key = context.cycle_key
        if not context.ready:
            detail = context.detail
        else:
            cycle_now = datetime.now(timezone.utc)
            result = worker.run_triggered(
                claimed.trigger_key,
                now=cycle_now,
                decision_as_of=context.decision_as_of,
            )
            worker.dispatch_pending()
            cycle_key = result.cycle_key
            snapshot_identifier = result.snapshot_identifier
            detail = result.detail
            succeeded = result.status == "completed"
            if succeeded:
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
