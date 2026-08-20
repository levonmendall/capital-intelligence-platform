"""Capability-aware release diagnostic coordination for production.

The operating CIO consumes independently qualified capability evidence, while release
certification continues to require complete all-market discovery and coverage. Capability
scope constrains execution eligibility only; it cannot narrow the research universe or turn
a partial-market cycle into a certified one.

This module also makes the release diagnostic single-flight: if another process already owns
the durable diagnostic request, a second launcher observes that owner instead of starting a
competing CIO child. Nothing here grants investment, specialist, construction, execution,
or real-money authority. Missing/stale evidence remains fail-closed.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from operations.capability_operating_evidence import (
    CapabilityOperatingEvidenceError,
    load_capability_operating_evidence,
)
from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic
from operations.reference_readiness import ReferenceReadinessManifest

_INSTALLED_ATTR = "_capability_scoped_release_diagnostic_installed"
_OWNER_LEASE_FILENAME = "manual-cio-diagnostic-owner.json"
_DEFAULT_DIAGNOSTIC_TIMEOUT_SECONDS = 1800.0
_COALESCE_GRACE_SECONDS = 30.0
_RESOURCE_LIMIT_RETURN_CODE = 125
_BUSY_RETURN_CODE = 3


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def capability_scoped_operation_enabled(values: Mapping[str, str]) -> bool:
    explicit = values.get("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION")
    if explicit is not None and str(explicit).strip():
        return _truthy(explicit)
    return _truthy(values.get("RENDER"))


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _asset_class_name(instrument: object) -> str:
    raw = getattr(instrument, "execution_asset_class", None)
    value = getattr(raw, "value", raw)
    normalized = str(value or "unknown").strip().lower()
    return normalized or "unknown"


def load_capability_operating_reference_manifest(
    values: MutableMapping[str, str],
) -> ReferenceReadinessManifest:
    """Validate fresh operating evidence and expose coordination metadata.

    Complete all-market evidence remains the release-wide certification boundary. This
    adapter separately proves that the exact operating universe is backed by a fresh,
    immutable capability snapshot before the CIO child can consume it.
    """

    cutoff = datetime.now(timezone.utc)
    try:
        operating = load_capability_operating_evidence(
            cutoff=cutoff,
            values=values,
        )
    except CapabilityOperatingEvidenceError as error:
        raise RuntimeError(
            f"capability operating evidence is not ready for the CIO watchdog: {error}"
        ) from error

    instruments = tuple(operating.universe.instruments)
    if not instruments:
        raise RuntimeError("capability operating evidence contains no operable instruments")

    counts: dict[str, int] = {}
    for instrument in instruments:
        name = _asset_class_name(instrument)
        counts[name] = counts.get(name, 0) + 1

    values["CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"] = operating.snapshot_id
    return ReferenceReadinessManifest(
        manifest_id=f"capability-operating:{operating.snapshot_id}",
        release=_release(values),
        captured_at=operating.as_of,
        config_fingerprint=f"capability-operating:{operating.snapshot_id}",
        eodhd_exchanges=(),
        futures_roots=(),
        catalog_counts=tuple(sorted(counts.items())),
        path=operating.state_path,
    )


def _owner_lease_path(values: Mapping[str, str]) -> Path:
    configured = str(
        values.get("CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PATH") or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().parent / _OWNER_LEASE_FILENAME
    data_root = Path(
        str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database")
    ).expanduser()
    return data_root / _OWNER_LEASE_FILENAME


def _owner_payload(values: Mapping[str, str]) -> Mapping[str, object] | None:
    try:
        payload = json.loads(_owner_lease_path(values).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _process_alive(pid: object) -> bool:
    if isinstance(pid, bool):
        return False
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    return value > 0 and Path(f"/proc/{value}").exists()


def _active_owner_exists(request_id: str, values: Mapping[str, str]) -> bool:
    payload = _owner_payload(values)
    return bool(
        payload is not None
        and str(payload.get("request_id") or "") == request_id
        and _process_alive(payload.get("pid"))
    )


def _diagnostic_timeout_seconds(values: Mapping[str, str]) -> float:
    raw = str(
        values.get("CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS") or ""
    ).strip()
    if not raw:
        return _DEFAULT_DIAGNOSTIC_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_DIAGNOSTIC_TIMEOUT_SECONDS
    return value if value > 0 else _DEFAULT_DIAGNOSTIC_TIMEOUT_SECONDS


def _coalesce_running_diagnostic(
    values: MutableMapping[str, str],
    *,
    publish_audit: Callable[[MutableMapping[str, str]], object],
    refresh_seconds: float,
) -> int | None:
    """Observe an already-owned diagnostic instead of launching a competing child."""

    existing = latest_manual_cio_diagnostic(values=values)
    if (
        existing is None
        or existing.state != "in_progress"
        or not _active_owner_exists(existing.request_id, values)
    ):
        return None

    expected_requester = f"render-release:{_release(values)}"
    deadline = time.monotonic() + _diagnostic_timeout_seconds(values) + _COALESCE_GRACE_SECONDS
    sleep_seconds = max(0.1, min(float(refresh_seconds), 5.0))

    while time.monotonic() < deadline:
        publish_audit(values)
        current = latest_manual_cio_diagnostic(values=values)
        if current is None:
            return None
        if current.request_id != existing.request_id:
            return None
        if current.state == "completed":
            return 0 if current.requested_by == expected_requester else _BUSY_RETURN_CODE
        if current.state == "failed":
            return _BUSY_RETURN_CODE
        if current.state != "in_progress":
            return None
        if not _active_owner_exists(current.request_id, values):
            return None
        time.sleep(sleep_seconds)

    return _RESOURCE_LIMIT_RETURN_CODE


def _capability_release_environment(
    original: Callable[[MutableMapping[str, str]], dict[str, str]],
    values: MutableMapping[str, str],
) -> dict[str, str]:
    diagnostic = original(values)
    if not capability_scoped_operation_enabled(values):
        return diagnostic
    diagnostic.update(
        {
            "CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION": "true",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY": "true",
            "CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE": "true",
            "CAPITAL_INTELLIGENCE_RUN_COMPREHENSIVE_DISCOVERY": "true",
            "CAPITAL_INTELLIGENCE_DIAGNOSTIC_ALLOW_COMPREHENSIVE_DISCOVERY": "true",
        }
    )
    return diagnostic


def install(memory_safe) -> None:
    """Install single-flight diagnostics without weakening all-market certification."""

    render_bootstrap = memory_safe.render_bootstrap
    if getattr(render_bootstrap, _INSTALLED_ATTR, False):
        return

    original_environment = render_bootstrap._release_diagnostic_environment
    original_run_with_audit = render_bootstrap._run_release_diagnostic_with_live_audit

    def release_environment(values: MutableMapping[str, str]) -> dict[str, str]:
        return _capability_release_environment(original_environment, values)

    def run_with_live_audit(
        command: Sequence[str],
        *,
        diagnostic_values: MutableMapping[str, str],
        refresh_seconds: float = 15.0,
    ) -> int:
        if capability_scoped_operation_enabled(diagnostic_values):
            coalesced = _coalesce_running_diagnostic(
                diagnostic_values,
                publish_audit=render_bootstrap._publish_release_diagnostic_audit,
                refresh_seconds=refresh_seconds,
            )
            if coalesced is not None:
                current = latest_manual_cio_diagnostic(values=diagnostic_values)
                render_bootstrap._log(
                    "manual_cio_release_diagnostic_singleflight_observed",
                    release=_release(diagnostic_values),
                    request_id=None if current is None else current.request_id,
                    request_state=None if current is None else current.state,
                    observed_return_code=coalesced,
                    competing_child_started=False,
                    complete_all_market_coverage_required=True,
                    capability_operating_evidence_required=True,
                    paper_only=True,
                    real_money_authorized=False,
                )
                return coalesced
        return original_run_with_audit(
            command,
            diagnostic_values=diagnostic_values,
            refresh_seconds=refresh_seconds,
        )

    render_bootstrap._release_diagnostic_environment = release_environment
    render_bootstrap._run_release_diagnostic_with_live_audit = run_with_live_audit
    setattr(render_bootstrap, _INSTALLED_ATTR, True)


__all__ = [
    "capability_scoped_operation_enabled",
    "install",
    "load_capability_operating_reference_manifest",
]
