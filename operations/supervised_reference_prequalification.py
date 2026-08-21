"""Supervise reusable reference acquisition at the individual component boundary.

Reference readiness persists release-independent lane components. Provider-facing directory
and futures work is executed in fresh, killable processes, while the controller carries
only small progress and manifest metadata. Exact-release binding is also isolated so the
controller never needs the full global reference catalog resident in memory.

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
_BINDING = "reference-binding"


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


def _directory_lanes(
    active_lanes: frozenset[CandidateAssetClass],
) -> tuple[CandidateAssetClass, ...]:
    """Return every scheduled EODHD-backed lane without imposing a coverage cap."""

    return tuple(
        sorted(
            active_lanes & _generalized._EODHD_REFERENCE_LANES,
            key=lambda item: item.value,
        )
    )


def _missing_required_directory_lanes(
    component: Mapping[str, object],
    *,
    active_lanes: frozenset[CandidateAssetClass],
) -> tuple[str, ...]:
    """Compatibility helper: identify scheduled EODHD lanes missing from an aggregate."""

    required = _directory_lanes(active_lanes)
    try:
        catalogs = _legacy._component_catalogs(component)
    except _legacy.ReferenceReadinessError:
        return tuple(item.value for item in required)
    return tuple(item.value for item in required if not catalogs.get(item.value))


def _directory_lane_component(lane: CandidateAssetClass) -> str:
    return f"{_DIRECTORY}:{lane.value}"


def _load_asset_component(
    values: Mapping[str, str],
    *,
    discovery,
    config,
    lane: CandidateAssetClass,
    timestamp: datetime,
) -> Mapping[str, object] | None:
    payload = _generalized.load_asset_reference_component(
        values,
        asset_class=lane,
        as_of=timestamp,
        config_fingerprint=_generalized._lane_config_fingerprint(config, lane),
        coverage=_generalized._lane_coverage(discovery, config, lane),
    )
    if payload is None or not _generalized._component_records(payload):
        return None
    return payload


def _collect_directory_lane(
    *,
    values: Mapping[str, str],
    discovery,
    config,
    policy,
    timestamp: datetime,
    lane: CandidateAssetClass,
) -> None:
    """Collect and persist exactly one EODHD-backed lane inside a fresh child process."""

    provider = discovery._base._legacy.build_eodhd_provider()
    catalogs = discovery._base._catalog_from_eodhd(
        as_of=timestamp,
        config=config,
        provider=provider,
        policy=policy,
        requested_asset_classes=frozenset({lane}),
    )
    records = tuple(catalogs.get(lane, ()))
    if not records:
        raise _plane.ContinuousEvidencePlaneError(
            "reference directory lane is empty; "
            f"failure_type=incomplete_lane_catalog; lane={lane.value}"
        )
    serialized = tuple(_legacy._record_payload(item) for item in records)
    _generalized.store_asset_reference_component(
        values,
        asset_class=lane,
        captured_at=timestamp,
        config_fingerprint=_generalized._lane_config_fingerprint(config, lane),
        coverage=_generalized._lane_coverage(discovery, config, lane),
        records=serialized,
        metadata={"collector": "eodhd_directory"},
    )


def _collect_futures_lane(
    *,
    values: Mapping[str, str],
    discovery,
    config,
    timestamp: datetime,
) -> None:
    """Collect and persist futures reference records without creating an aggregate in parent."""

    roots = _legacy._futures_roots(config)
    provider = _providers(values)
    records = tuple(
        discovery._base._legacy._futures_catalog(
            as_of=timestamp,
            config=config,
            massive_futures_provider=provider,
        )
    )
    serialized = tuple(_legacy._record_payload(item) for item in records)
    _legacy._validate_future_records(serialized, roots)
    _generalized.store_asset_reference_component(
        values,
        asset_class=CandidateAssetClass.FUTURE,
        captured_at=timestamp,
        config_fingerprint=_generalized._lane_config_fingerprint(
            config, CandidateAssetClass.FUTURE
        ),
        coverage=_generalized._lane_coverage(
            discovery, config, CandidateAssetClass.FUTURE
        ),
        records=serialized,
        metadata={"collector": "futures_contracts"},
    )


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


def _manifest_metadata(manifest: _legacy.ReferenceReadinessManifest) -> dict[str, object]:
    """Transport only small manifest metadata across the binding process boundary."""

    return {
        "manifest_id": manifest.manifest_id,
        "release": manifest.release,
        "captured_at": manifest.captured_at.isoformat(),
        "config_fingerprint": manifest.config_fingerprint,
        "eodhd_exchanges": list(manifest.eodhd_exchanges),
        "futures_roots": list(manifest.futures_roots),
        "catalog_counts": [list(item) for item in manifest.catalog_counts],
        "path": str(manifest.path),
        "paper_only": True,
        "real_money_authorized": False,
    }


def _bind_release_in_child(
    *,
    values: MutableMapping[str, str],
    timestamp: datetime,
    discovery,
    config,
    option_ready_underlyings: int,
) -> Mapping[str, object]:
    """Build compatibility artifacts in a fresh process, then return metadata only."""

    _generalized._write_asset_registry(
        values=values,
        timestamp=datetime.now(timezone.utc),
        discovery=discovery,
        config=config,
        option_ready_underlyings=option_ready_underlyings,
    )
    manifest = _strict_release_binding(values, minimum_cutoff=timestamp)
    return _manifest_metadata(manifest)


def _manifest_from_metadata(
    values: MutableMapping[str, str],
    payload: Mapping[str, object],
) -> _legacy.ReferenceReadinessManifest:
    """Reconstruct the small manifest handle without loading the global catalog in parent."""

    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        raise _plane.ContinuousEvidencePlaneError(
            "reference binding returned invalid governance metadata; "
            "failure_type=release_binding_failure"
        )
    try:
        captured_at = datetime.fromisoformat(
            str(payload["captured_at"]).replace("Z", "+00:00")
        )
        counts = tuple(
            (str(item[0]), int(item[1]))
            for item in payload["catalog_counts"]
        )
        manifest = _legacy.ReferenceReadinessManifest(
            manifest_id=str(payload["manifest_id"]),
            release=str(payload["release"]),
            captured_at=_aware(captured_at, field_name="reference_manifest_captured_at"),
            config_fingerprint=str(payload["config_fingerprint"]),
            eodhd_exchanges=tuple(str(item) for item in payload["eodhd_exchanges"]),
            futures_roots=tuple(str(item) for item in payload["futures_roots"]),
            catalog_counts=counts,
            path=Path(str(payload["path"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise _plane.ContinuousEvidencePlaneError(
            "reference binding returned invalid manifest metadata; "
            "failure_type=release_binding_failure"
        ) from error
    if manifest.release != _release(values) or not manifest.manifest_id or not manifest.path.is_file():
        raise _plane.ContinuousEvidencePlaneError(
            "reference binding metadata does not match the active release; "
            "failure_type=release_binding_failure"
        )
    values[_legacy._MANIFEST_PATH_ENV] = str(manifest.path)
    values[_legacy._MANIFEST_ID_ENV] = manifest.manifest_id
    return manifest


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
    directory_lanes = _directory_lanes(active_lanes)
    required_components = (_DIRECTORY,) + (
        (_FUTURES,) if CandidateAssetClass.FUTURE in active_lanes else ()
    )
    components: dict[str, Mapping[str, object]] = {}

    _write_progress(
        values=values,
        cutoff=timestamp,
        required_components=required_components,
        components=components,
        active_component=None,
        state="qualifying",
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

    directory_reused = True
    directory_failure: Mapping[str, object] | None = None
    for lane in directory_lanes:
        if _load_asset_component(
            values,
            discovery=discovery,
            config=config,
            lane=lane,
            timestamp=timestamp,
        ) is not None:
            continue

        directory_reused = False
        lane_component = _directory_lane_component(lane)
        _write_progress(
            values=values,
            cutoff=timestamp,
            required_components=required_components,
            components=components,
            active_component=lane_component,
            state="qualifying",
        )
        try:
            _run_component(
                values=values,
                component=lane_component,
                provider="eodhd",
                operation=lambda lane=lane: _collect_directory_lane(
                    values=values,
                    discovery=discovery,
                    config=config,
                    policy=policy,
                    timestamp=timestamp,
                    lane=lane,
                ),
                return_value=False,
            )
            if _load_asset_component(
                values,
                discovery=discovery,
                config=config,
                lane=lane,
                timestamp=datetime.now(timezone.utc),
            ) is None:
                raise _plane.ContinuousEvidencePlaneError(
                    "reference directory lane worker completed without a qualified checkpoint; "
                    f"failure_type=missing_checkpoint; lane={lane.value}"
                )
        except _plane.ContinuousEvidencePlaneError as error:
            directory_failure = _component_row(
                lane_component,
                provider="eodhd",
                state="timed-out" if _failure_type(error) == "timeout" else "failed",
                required=True,
                failure_type=_failure_type(error),
            )
            break

    if directory_failure is not None:
        components[_DIRECTORY] = directory_failure
    else:
        components[_DIRECTORY] = _component_row(
            _DIRECTORY,
            provider="eodhd",
            state="reused" if directory_reused else "qualified",
            required=True,
        )
    _write_progress(
        values=values,
        cutoff=timestamp,
        required_components=required_components,
        components=components,
        active_component=None,
        state="qualifying",
    )

    futures_ready = CandidateAssetClass.FUTURE not in active_lanes
    if CandidateAssetClass.FUTURE in active_lanes:
        futures_payload = _load_asset_component(
            values,
            discovery=discovery,
            config=config,
            lane=CandidateAssetClass.FUTURE,
            timestamp=timestamp,
        )
        if futures_payload is not None:
            try:
                _legacy._validate_future_records(
                    _generalized._component_records(futures_payload),
                    _legacy._futures_roots(config),
                )
                futures_ready = True
                components[_FUTURES] = _component_row(
                    _FUTURES, provider="cme-massive", state="reused", required=True
                )
            except _legacy.ReferenceReadinessError:
                futures_payload = None
        if futures_payload is None:
            _write_progress(
                values=values,
                cutoff=timestamp,
                required_components=required_components,
                components=components,
                active_component=_FUTURES,
                state="qualifying",
            )
            try:
                _run_component(
                    values=values,
                    component=_FUTURES,
                    provider="cme-massive",
                    operation=lambda: _collect_futures_lane(
                        values=values,
                        discovery=discovery,
                        config=config,
                        timestamp=timestamp,
                    ),
                    return_value=False,
                )
                futures_payload = _load_asset_component(
                    values,
                    discovery=discovery,
                    config=config,
                    lane=CandidateAssetClass.FUTURE,
                    timestamp=datetime.now(timezone.utc),
                )
                if futures_payload is None:
                    raise _plane.ContinuousEvidencePlaneError(
                        "reference futures worker completed without a qualified checkpoint; "
                        "failure_type=missing_checkpoint"
                    )
                _legacy._validate_future_records(
                    _generalized._component_records(futures_payload),
                    _legacy._futures_roots(config),
                )
                futures_ready = True
                components[_FUTURES] = _component_row(
                    _FUTURES, provider="cme-massive", state="qualified", required=True
                )
            except (_plane.ContinuousEvidencePlaneError, _legacy.ReferenceReadinessError) as error:
                futures_ready = False
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
    if failed_required or missing_required or not futures_ready:
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

    _write_progress(
        values=values,
        cutoff=timestamp,
        required_components=required_components,
        components=components,
        active_component=_BINDING,
        state="qualifying",
    )
    try:
        metadata = _run_component(
            values=values,
            component=_BINDING,
            provider="persistent-reference-components",
            operation=lambda: _bind_release_in_child(
                values=values,
                timestamp=timestamp,
                discovery=discovery,
                config=config,
                option_ready_underlyings=option_ready_underlyings,
            ),
            return_value=True,
        )
        if not isinstance(metadata, Mapping):
            raise _plane.ContinuousEvidencePlaneError(
                "reference binding returned no manifest metadata; "
                "failure_type=release_binding_failure"
            )
        manifest = _manifest_from_metadata(values, metadata)
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
