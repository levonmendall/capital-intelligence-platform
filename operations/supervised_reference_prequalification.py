"""Supervise reusable reference acquisition at the individual component boundary.

Reference readiness already persists release-independent lane components. This module
finishes that architecture by giving each provider-facing reference component its own
killable execution budget and by publishing one credential-safe progress manifest that
survives a later component failure. The aggregate controller itself is never placed in a
second process-group timeout.

Nothing in this module has investment, specialist, construction, execution, or real-money
authority. Required reference failures remain fail-closed; the option-definition prewarm
remains an optimization and cannot authorize or block a CIO decision on its own.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, MutableMapping

from cio import CandidateAssetClass
from operations import continuous_evidence_plane as _plane
from operations import generalized_reference_readiness as _generalized
from operations import reference_readiness as _legacy
from operations import release_reference_binding as _release_binding
from operations.supervised_component_execution import (
    SupervisedComponentExecutionError,
    SupervisedComponentTimeout,
    run_supervised_component,
)


_PROGRESS_SCHEMA = "reference-prequalification-progress.v1"
_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_REFERENCE_COMPONENT_TIMEOUT_SECONDS"
_LEGACY_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_REFERENCE_TIMEOUT_SECONDS"
_DEFAULT_TIMEOUT_SECONDS = 120.0
_DIRECTORY = "reference-directories"
_FUTURES = "reference-futures-contracts"
_OPTIONS = "option-reference-definitions"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "").strip())
    return normalized.strip("-.") or "unknown"


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def reference_prequalification_progress_path(values: Mapping[str, str]) -> Path:
    data_root = Path(str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database")).expanduser()
    return data_root / "reference_readiness" / "prequalification-latest.json"


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(dict(payload), sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise _plane.ContinuousEvidencePlaneError(
            f"reference prequalification progress cannot be persisted: {error}"
        ) from error


def load_reference_prequalification_progress(
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object] | None:
    resolved = os.environ if values is None else values
    path = reference_prequalification_progress_path(resolved)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != _PROGRESS_SCHEMA:
        return None
    if str(payload.get("release") or "") != _release(resolved):
        return None
    if payload.get("credential_safe") is not True:
        return None
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        return None
    return dict(payload)


def _timeout_seconds(values: Mapping[str, str]) -> float:
    raw = str(
        values.get(_TIMEOUT_ENV)
        or os.getenv(_TIMEOUT_ENV, "")
        or values.get(_LEGACY_TIMEOUT_ENV)
        or os.getenv(_LEGACY_TIMEOUT_ENV, "")
        or ""
    ).strip()
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ValueError(f"{_TIMEOUT_ENV} must be numeric") from error
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError(f"{_TIMEOUT_ENV} must be positive")
    return timeout


def _component_row(
    component: str,
    *,
    provider: str,
    state: str,
    required: bool,
    failure_type: str | None = None,
) -> dict[str, object]:
    return {
        "component": _safe(component),
        "provider": _safe(provider),
        "state": _safe(state),
        "required": bool(required),
        "failure_type": None if failure_type is None else _safe(failure_type),
    }


def _write_progress(
    *,
    values: Mapping[str, str],
    cutoff: datetime,
    required_components: tuple[str, ...],
    components: Mapping[str, Mapping[str, object]],
    active_component: str | None,
    state: str,
) -> None:
    rows = [dict(components[name]) for name in components]
    required_rows = [row for row in rows if row.get("required") is True]
    qualified = [row for row in required_rows if row.get("state") in {"qualified", "reused"}]
    reused = [row for row in required_rows if row.get("state") == "reused"]
    newly_qualified = [row for row in required_rows if row.get("state") == "qualified"]
    failed = [row for row in required_rows if row.get("state") in {"failed", "timed-out", "invalid"}]
    pending = [name for name in required_components if name not in components]
    failures = [
        {
            "component": row["component"],
            "provider": row["provider"],
            "failure_type": row.get("failure_type") or "unknown",
        }
        for row in rows
        if row.get("state") in {"failed", "timed-out", "invalid"}
    ]
    _atomic_json(
        reference_prequalification_progress_path(values),
        {
            "schema_version": _PROGRESS_SCHEMA,
            "release": _release(values),
            "state": _safe(state),
            "cutoff": cutoff.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "required_count": len(required_components),
            "qualified_count": len(qualified),
            "reused_count": len(reused),
            "newly_qualified_count": len(newly_qualified),
            "failed_count": len(failed),
            "pending_count": len(pending),
            "active_component": None if active_component is None else _safe(active_component),
            "components": rows,
            "failures": failures,
            "credential_safe": True,
            "decision_evidence_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        },
    )


def _run_component(
    *,
    values: Mapping[str, str],
    component: str,
    provider: str,
    operation,
    return_value: bool,
):
    try:
        return run_supervised_component(
            component=component,
            operation=operation,
            timeout_seconds=_timeout_seconds(values),
            return_value=return_value,
        )
    except SupervisedComponentTimeout as error:
        raise _plane.ContinuousEvidencePlaneError(
            "reference component acquisition timed out; failure_type=timeout; "
            f"component={_safe(component)}; provider={_safe(provider)}"
        ) from error
    except SupervisedComponentExecutionError as error:
        raise _plane.ContinuousEvidencePlaneError(
            "reference component acquisition failed; failure_type=provider_failure; "
            f"component={_safe(component)}; provider={_safe(provider)}; {error}"
        ) from error


def _failure_type(error: BaseException) -> str:
    detail = str(error)
    match = re.search(r"(?:^|;\s*)failure_type=([^;\s]+)", detail)
    return _safe(match.group(1)) if match else "provider_failure"


def _providers(values: Mapping[str, str]):
    from operations.cme_futures_reference_runtime import install_cme_futures_reference_lineage
    from providers.cme_futures_reference_executable import CmeExecutableFuturesReferenceProvider
    from providers.massive_futures_reference_rate_resilient import MassiveFuturesReferenceProvider

    install_cme_futures_reference_lineage()
    return CmeExecutableFuturesReferenceProvider(
        fallback_provider=MassiveFuturesReferenceProvider(),
        values=values,
    )


def _missing_required_directory_lanes(
    component: Mapping[str, object],
    *,
    active_lanes: frozenset[CandidateAssetClass],
) -> tuple[str, ...]:
    """Return scheduled release lanes that cannot be bound from this aggregate component."""

    required = tuple(
        sorted(
            active_lanes & _generalized._EODHD_REFERENCE_LANES,
            key=lambda item: item.value,
        )
    )
    try:
        catalogs = _legacy._component_catalogs(component)
    except _legacy.ReferenceReadinessError:
        return tuple(item.value for item in required)
    return tuple(item.value for item in required if not catalogs.get(item.value))


def _strict_release_binding(
    values: MutableMapping[str, str],
    *,
    minimum_cutoff: datetime,
) -> _legacy.ReferenceReadinessManifest:
    """Require the exact release binder to consume the components before qualification."""

    binding_cutoff = max(
        _aware(minimum_cutoff, field_name="reference_binding_minimum_cutoff"),
        datetime.now(timezone.utc),
    )
    try:
        return _release_binding.bind_reference_manifest_from_components(
            values,
            now=binding_cutoff,
        )
    except _legacy.ReferenceReadinessError as error:
        raise _plane.ContinuousEvidencePlaneError(
            "reference prequalification components are not release-bindable; "
            f"failure_type=release_binding_failure; {error}"
        ) from error


def prepare_supervised_reference_prequalification(
    values: MutableMapping[str, str],
    *,
    now: datetime | None = None,
) -> _legacy.ReferenceReadinessManifest:
    """Qualify required reference components independently, then bind one manifest."""

    from operations import _comprehensive_market_discovery_v4 as discovery

    timestamp = _aware(now or datetime.now(timezone.utc), field_name="now")
    config = discovery._base.load_comprehensive_market_discovery_config()
    discovery._base._reject_evidence_only_eodhd_directories(config)
    policy = discovery.ComprehensiveMarketDiscoveryPolicy()
    active_lanes = discovery._base.scheduled_discovery_lanes(timestamp)
    active_lane_names = tuple(sorted(item.value for item in active_lanes))
    config_fingerprint = _legacy._fingerprint(_legacy._config_material(config))
    roots = _legacy._futures_roots(config)
    required_components = (_DIRECTORY,) + ((_FUTURES,) if CandidateAssetClass.FUTURE in active_lanes else ())
    components: dict[str, Mapping[str, object]] = {}

    _write_progress(
        values=values,
        cutoff=timestamp,
        required_components=required_components,
        components=components,
        active_component=None,
        state="qualifying",
    )

    _generalized._prime_legacy_components(
        values=values,
        timestamp=timestamp,
        discovery=discovery,
        config=config,
        active_lanes=active_lanes,
    )

    option_ready_underlyings = 0
    if CandidateAssetClass.OPTION in active_lanes:
        _write_progress(
            values=values,
            cutoff=timestamp,
            required_components=required_components,
            components=components,
            active_component=_OPTIONS,
            state="qualifying",
        )
        try:
            def option_operation():
                from operations.persistent_option_reference import prewarm_option_reference_definitions

                return prewarm_option_reference_definitions(
                    values,
                    as_of=timestamp,
                    config=config,
                    policy=policy,
                    force_refresh=False,
                )

            option_stats = _run_component(
                values=values,
                component=_OPTIONS,
                provider="alpaca-tradier-massive",
                operation=option_operation,
                return_value=True,
            )
            option_ready_underlyings = int(
                option_stats.get("ready_underlyings", 0)
                if isinstance(option_stats, Mapping)
                else 0
            )
            components[_OPTIONS] = _component_row(
                _OPTIONS,
                provider="alpaca-tradier-massive",
                state="qualified",
                required=False,
            )
        except (_plane.ContinuousEvidencePlaneError, OSError, TypeError, ValueError, RuntimeError) as error:
            components[_OPTIONS] = _component_row(
                _OPTIONS,
                provider="alpaca-tradier-massive",
                state="failed",
                required=False,
                failure_type=_failure_type(error),
            )
        _write_progress(
            values=values,
            cutoff=timestamp,
            required_components=required_components,
            components=components,
            active_component=None,
            state="qualifying",
        )

    directory_component = _legacy._validated_component(
        path=_legacy._component_path(values, _legacy._DIRECTORY_COMPONENT),
        component=_legacy._DIRECTORY_COMPONENT,
        timestamp=timestamp,
        values=values,
        config_fingerprint=config_fingerprint,
        active_lanes=active_lane_names,
        coverage=tuple(config.eodhd_exchange_codes),
    )
    if directory_component is not None and _missing_required_directory_lanes(
        directory_component,
        active_lanes=active_lanes,
    ):
        # A fresh/config-compatible aggregate can still be unusable by the exact-release
        # binder when one scheduled lane has no persisted records. Never call that reused.
        directory_component = None
    if directory_component is not None:
        components[_DIRECTORY] = _component_row(
            _DIRECTORY, provider="eodhd", state="reused", required=True
        )
    else:
        _write_progress(
            values=values,
            cutoff=timestamp,
            required_components=required_components,
            components=components,
            active_component=_DIRECTORY,
            state="qualifying",
        )
        try:
            eodhd_provider = discovery._base._legacy.build_eodhd_provider()
            _run_component(
                values=values,
                component=_DIRECTORY,
                provider="eodhd",
                operation=lambda: _legacy._collect_directory_component(
                    discovery=discovery,
                    timestamp=timestamp,
                    values=values,
                    config=config,
                    policy=policy,
                    provider=eodhd_provider,
                    active_lanes=active_lanes,
                    active_lane_names=active_lane_names,
                    config_fingerprint=config_fingerprint,
                ),
                return_value=False,
            )
            directory_component = _legacy._validated_component(
                path=_legacy._component_path(values, _legacy._DIRECTORY_COMPONENT),
                component=_legacy._DIRECTORY_COMPONENT,
                timestamp=datetime.now(timezone.utc),
                values=values,
                config_fingerprint=config_fingerprint,
                active_lanes=active_lane_names,
                coverage=tuple(config.eodhd_exchange_codes),
            )
            if directory_component is None:
                raise _plane.ContinuousEvidencePlaneError(
                    "reference directory worker completed without a qualified checkpoint"
                )
            missing_directory_lanes = _missing_required_directory_lanes(
                directory_component,
                active_lanes=active_lanes,
            )
            if missing_directory_lanes:
                raise _plane.ContinuousEvidencePlaneError(
                    "reference directory component is incomplete for scheduled release lanes; "
                    "failure_type=incomplete_lane_catalog; missing_lanes="
                    + ",".join(missing_directory_lanes)
                )
            components[_DIRECTORY] = _component_row(
                _DIRECTORY, provider="eodhd", state="qualified", required=True
            )
        except _plane.ContinuousEvidencePlaneError as error:
            components[_DIRECTORY] = _component_row(
                _DIRECTORY,
                provider="eodhd",
                state="timed-out" if _failure_type(error) == "timeout" else "failed",
                required=True,
                failure_type=_failure_type(error),
            )
        _write_progress(
            values=values,
            cutoff=timestamp,
            required_components=required_components,
            components=components,
            active_component=None,
            state="qualifying",
        )

    futures_component = None
    if CandidateAssetClass.FUTURE in active_lanes:
        futures_component = _legacy._validated_component(
            path=_legacy._component_path(values, _legacy._FUTURES_COMPONENT),
            component=_legacy._FUTURES_COMPONENT,
            timestamp=timestamp,
            values=values,
            config_fingerprint=config_fingerprint,
            active_lanes=active_lane_names,
            coverage=roots,
        )
        if futures_component is not None:
            try:
                _legacy._validate_future_records(
                    _legacy._component_catalogs(futures_component).get(
                        CandidateAssetClass.FUTURE.value, []
                    ),
                    roots,
                )
            except _legacy.ReferenceReadinessError:
                futures_component = None
        if futures_component is not None:
            components[_FUTURES] = _component_row(
                _FUTURES, provider="cme-massive", state="reused", required=True
            )
        else:
            _write_progress(
                values=values,
                cutoff=timestamp,
                required_components=required_components,
                components=components,
                active_component=_FUTURES,
                state="qualifying",
            )
            try:
                futures_provider = _providers(values)
                _run_component(
                    values=values,
                    component=_FUTURES,
                    provider="cme-massive",
                    operation=lambda: _legacy._collect_futures_component(
                        discovery=discovery,
                        timestamp=timestamp,
                        values=values,
                        config=config,
                        massive_futures_provider=futures_provider,
                        active_lane_names=active_lane_names,
                        config_fingerprint=config_fingerprint,
                        roots=roots,
                    ),
                    return_value=False,
                )
                futures_component = _legacy._validated_component(
                    path=_legacy._component_path(values, _legacy._FUTURES_COMPONENT),
                    component=_legacy._FUTURES_COMPONENT,
                    timestamp=datetime.now(timezone.utc),
                    values=values,
                    config_fingerprint=config_fingerprint,
                    active_lanes=active_lane_names,
                    coverage=roots,
                )
                if futures_component is None:
                    raise _plane.ContinuousEvidencePlaneError(
                        "reference futures worker completed without a qualified checkpoint"
                    )
                _legacy._validate_future_records(
                    _legacy._component_catalogs(futures_component).get(
                        CandidateAssetClass.FUTURE.value, []
                    ),
                    roots,
                )
                components[_FUTURES] = _component_row(
                    _FUTURES, provider="cme-massive", state="qualified", required=True
                )
            except (_plane.ContinuousEvidencePlaneError, _legacy.ReferenceReadinessError) as error:
                components[_FUTURES] = _component_row(
                    _FUTURES,
                    provider="cme-massive",
                    state="timed-out" if _failure_type(error) == "timeout" else "failed",
                    required=True,
                    failure_type=_failure_type(error),
                )
            _write_progress(
                values=values,
                cutoff=timestamp,
                required_components=required_components,
                components=components,
                active_component=None,
                state="qualifying",
            )

    failed_required = [
        row
        for row in components.values()
        if row.get("required") is True and row.get("state") not in {"qualified", "reused"}
    ]
    missing_required = [name for name in required_components if name not in components]
    if failed_required or missing_required or directory_component is None or (
        CandidateAssetClass.FUTURE in active_lanes and futures_component is None
    ):
        _write_progress(
            values=values,
            cutoff=timestamp,
            required_components=required_components,
            components=components,
            active_component=None,
            state="incomplete",
        )
        first = failed_required[0] if failed_required else {
            "component": missing_required[0] if missing_required else "reference-unknown",
            "provider": "unknown",
            "failure_type": "missing_checkpoint",
        }
        raise _plane.ContinuousEvidencePlaneError(
            "reference prequalification remains incomplete; "
            f"required_count={len(required_components)}; "
            f"qualified_count={sum(1 for row in components.values() if row.get('required') is True and row.get('state') in {'qualified', 'reused'})}; "
            f"failed_count={len(failed_required) + len(missing_required)}; "
            f"component={first.get('component')}; provider={first.get('provider')}; "
            f"failure_type={first.get('failure_type') or 'unknown'}"
        )

    manifest = _legacy._bind_manifest(
        values=values,
        timestamp=timestamp,
        release=_legacy._release(values),
        config=config,
        config_fingerprint=config_fingerprint,
        active_lane_names=active_lane_names,
        directory_component=directory_component,
        futures_component=futures_component,
        roots=roots,
    )
    _generalized._capture_manifest_components(
        values=values,
        manifest=manifest,
        discovery=discovery,
        config=config,
    )
    try:
        manifest = _strict_release_binding(values, minimum_cutoff=timestamp)
    except _plane.ContinuousEvidencePlaneError:
        _write_progress(
            values=values,
            cutoff=timestamp,
            required_components=required_components,
            components=components,
            active_component=None,
            state="incomplete",
        )
        raise
    _generalized._write_asset_registry(
        values=values,
        timestamp=datetime.now(timezone.utc),
        discovery=discovery,
        config=config,
        option_ready_underlyings=option_ready_underlyings,
    )
    _write_progress(
        values=values,
        cutoff=timestamp,
        required_components=required_components,
        components=components,
        active_component=None,
        state="qualified",
    )
    return manifest


__all__ = [
    "load_reference_prequalification_progress",
    "prepare_supervised_reference_prequalification",
    "reference_prequalification_progress_path",
]
