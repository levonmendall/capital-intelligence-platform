"""Compact coordinator for end-to-end transactional comprehensive-discovery lanes.

Each market lane is completed in one fresh child interpreter: governed catalog
reconstruction, certified merge, provider publication, terminal screening, compact durable
checkpoint, cache release, and child exit.  The coordinator retains only descriptors and
never persists a raw catalog shard across lane boundaries.

The next lane is not launched until the prior transaction has exited, its integrity-
protected state is readable, and advisory clean-page reclamation has had a chance to run.
This keeps cgroup pressure a function of the largest lane rather than the number of lanes
already processed.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from operations import bounded_comprehensive_discovery_spool as _bounded
from operations import comprehensive_discovery_input_spool as _legacy
from operations import comprehensive_discovery_structural_cache as _structural
from operations import continuous_evidence_plane as _evidence_plane
from operations import lane_local_comprehensive_discovery_spool as _lane_local
from operations import transactional_comprehensive_discovery_lane as _transaction
from operations.post_lane_cache_reclamation import (
    run_lane_exit_exact_spool_cache_reclamation,
)
from operations.publication_lane_cache_reclamation import (
    run_publication_lane_cache_reclamation,
)

_MODULE = "operations.transactional_comprehensive_discovery_lane"
_PROCESS_TERMINATE_GRACE_SECONDS = 2.0


def _record_transaction_start(path: Path, values: Mapping[str, str], *, asset_class: str, index: int) -> None:
    try:
        from operations import manual_cio_diagnostic as diagnostic

        diagnostic.record_manual_cio_diagnostic_progress(
            f"bounded_spool_catalog_lane:{asset_class}"
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from operations.lane_local_watchdog_progress import (
            record_active_lane_watchdog_progress,
        )

        record_active_lane_watchdog_progress(
            path,
            values,
            action="catalog-lane",
            asset_class=asset_class,
            index=index,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def _publish_transaction_completion(
    *,
    asset_class: str,
    raw_record_count: int,
    record_count: int,
    peak_rss_bytes: int,
) -> None:
    from operations import comprehensive_market_discovery as facade

    core = facade._core
    core.record_manual_cio_diagnostic_progress(
        f"bounded_spool_catalog_lane_complete:{asset_class}",
        metrics={
            "catalog_records": int(raw_record_count),
            "peak_rss_bytes": int(peak_rss_bytes),
        },
    )
    core.record_manual_cio_diagnostic_progress(
        f"bounded_spool_publication_lane_complete:{asset_class}",
        metrics={
            "catalog_records": int(record_count),
            "peak_rss_bytes": int(peak_rss_bytes),
        },
    )


def run_post_lane_cache_reclamation(
    values: Mapping[str, str],
    *,
    node_id: str,
    asset_class: str,
    index: int = 0,
) -> dict[str, object]:
    """Preserve the established post-lane hook with bounded two-step reclamation.

    The coordinator has historically exposed one monkeypatchable post-lane reclamation
    seam. Keep that contract intact: first release the exact completed spool in the parent,
    then run the broader ownership-validated data-root clean-page pass in a disposable
    child. The child must exit before the next serialized lane can launch, so its scan heap
    cannot accumulate in the long-lived comprehensive coordinator. The caller remains
    responsible for fail-soft behavior.
    """

    exact_spool = run_lane_exit_exact_spool_cache_reclamation(
        values,
        node_id=node_id,
        asset_class=asset_class,
    )
    broad = run_publication_lane_cache_reclamation(
        values,
        asset_class=asset_class,
        index=index,
    )
    return {
        "exact_release_spool": exact_spool,
        "broad_reclamation": broad,
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


def _remaining_epoch_seconds(
    *,
    decision_epoch: datetime,
    values: Mapping[str, str],
    now: datetime | None = None,
) -> float:
    """Return only the unused portion of the existing evidence-plane freshness epoch."""

    timestamp = _legacy._aware(decision_epoch, field_name="decision_epoch")
    current = _legacy._aware(
        now or datetime.now(timezone.utc),
        field_name="comprehensive_discovery_now",
    )
    expiry = timestamp + timedelta(seconds=_evidence_plane._max_age_seconds(values))
    return (expiry - current).total_seconds()


def _process_tree_alive(process: subprocess.Popen[bytes]) -> bool:
    if os.name != "posix":
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return process.poll() is None
    except PermissionError:
        return True
    return True


def _signal_process_tree(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, sig)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    if process.poll() is not None:
        return
    if sig == signal.SIGKILL:
        process.kill()
    else:
        process.terminate()


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float = _PROCESS_TERMINATE_GRACE_SECONDS,
) -> tuple[bool, bool]:
    """Terminate every process in the disposable lane session and reap its leader."""

    if not _process_tree_alive(process):
        return False, False
    terminated = True
    killed = False
    _signal_process_tree(process, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, float(grace_seconds))
    while _process_tree_alive(process) and time.monotonic() < deadline:
        time.sleep(0.01)
    if _process_tree_alive(process):
        killed = True
        _signal_process_tree(process, signal.SIGKILL)
    try:
        process.wait(timeout=max(0.1, float(grace_seconds) + 0.1))
    except subprocess.TimeoutExpired:
        killed = True
        _signal_process_tree(process, signal.SIGKILL)
        process.wait(timeout=1.0)
    return terminated, killed


def _run_lane_transaction(
    path: Path,
    values: Mapping[str, str],
    *,
    asset_class: str,
    index: int,
    decision_epoch: datetime,
) -> Mapping[str, object]:
    """Run one complete lane child inside the remaining evidence freshness budget."""

    _record_transaction_start(path, values, asset_class=asset_class, index=index)
    remaining_seconds = _remaining_epoch_seconds(
        decision_epoch=decision_epoch,
        values=values,
    )
    if remaining_seconds <= 0.0:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "transactional comprehensive lane refused expired evidence epoch; "
            f"asset_class={asset_class}"
        )
    command = (
        sys.executable,
        "-m",
        _MODULE,
        "--request",
        str(path),
        "--asset-class",
        asset_class,
        "--index",
        str(index),
    )
    process = subprocess.Popen(
        command,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=dict(values),
        start_new_session=(os.name == "posix"),
    )
    try:
        try:
            return_code = int(process.wait(timeout=max(0.001, remaining_seconds)))
        except subprocess.TimeoutExpired as error:
            _terminate_process_tree(process)
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "transactional comprehensive lane exceeded the existing evidence freshness epoch; "
                f"asset_class={asset_class}; freshness_seconds="
                f"{_evidence_plane._max_age_seconds(values):.3f}"
            ) from error
    finally:
        # Defensive cleanup also covers cancellation/exception paths. A successful child
        # has already exited and this is a no-op; no nested provider worker may survive an
        # expired or aborted attempt.
        if _process_tree_alive(process):
            _terminate_process_tree(process)

    if return_code != 0:
        failure = _legacy.load_failure(path)
        if failure is None:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "transactional comprehensive lane exited without attribution; "
                f"asset_class={asset_class}; return_code={return_code}"
            )
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "transactional comprehensive lane failed; "
            f"asset_class={asset_class}; "
            f"stage={failure.get('failure_stage')}; "
            f"failure_type={failure.get('error_type')}; "
            f"detail={failure.get('error_detail')}"
        )

    state = _bounded._load_stage_state(
        path,
        _transaction._transaction_state_name(index),
    )
    if state.get("schema_version") != _transaction._TRANSACTION_SCHEMA:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"transactional lane state schema changed for {asset_class}"
        )
    if state.get("transactional_lane_compaction") is not True:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"transactional lane did not attest compaction for {asset_class}"
        )
    if state.get("raw_catalog_persisted") is not False:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"transactional lane retained raw catalog scratch for {asset_class}"
        )
    if str(state.get("asset_class") or "") != asset_class:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"transactional lane identity changed for {asset_class}"
        )
    if state.get("scheduled") is True:
        if state.get("provider_publication_verified") is not True:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"transactional scheduled lane lacks verified provider publication for {asset_class}"
            )
        publication_path = Path(str(state.get("provider_preselection_path") or ""))
        if not publication_path.is_file() or publication_path.is_symlink():
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"transactional scheduled lane provider publication is unavailable for {asset_class}"
            )

    # The lane child is fully gone and the compact transaction checkpoint above has been
    # integrity-validated. The established post-lane hook first advises only the exact
    # release spool in this parent, then launches one bounded broad reclaimer child. That
    # child must exit before completion is published or another serialized lane can launch,
    # which returns its scan heap to the OS while preserving the clean-cache benefit.
    try:
        run_post_lane_cache_reclamation(
            values,
            node_id=f"comprehensive-lane:{asset_class}",
            asset_class=asset_class,
            index=index,
        )
    except Exception:  # noqa: BLE001 - cache hygiene cannot change evidence state.
        pass

    _publish_transaction_completion(
        asset_class=asset_class,
        raw_record_count=int(state.get("raw_record_count") or 0),
        record_count=int(state.get("record_count") or 0),
        peak_rss_bytes=int(state.get("peak_rss_bytes") or 0),
    )
    return state


def build_spool(
    request_path: str | Path,
    *,
    values: Mapping[str, str] | None = None,
) -> Path:
    """Build one manifest from compact, restartable, end-to-end lane transactions."""

    resolved_values = dict(os.environ if values is None else values)
    path = Path(request_path).expanduser()
    try:
        request, policy = _bounded._validate_request(path, resolved_values)
        if _legacy.manifest_available(path):
            return _legacy._manifest_path(path)
        decision_epoch = _legacy._parse_timestamp(
            request.get("decision_epoch"),
            field_name="decision_epoch",
        )

        # Compute the reference-content identity once in the parent. Every finite child
        # receives the same verified digest, avoiding repeated full-manifest reads while
        # allowing a freshly bound manifest with identical structural catalogs to reuse the
        # prior structural cache. Failure only disables advisory reuse; canonical discovery
        # remains the fail-closed authority.
        resolved_values.pop(_structural._REFERENCE_STRUCTURAL_FINGERPRINT_ENV, None)
        try:
            _structural.bind_reference_structural_fingerprint(resolved_values)
        except (OSError, RuntimeError, TypeError, ValueError):
            resolved_values.pop(_structural._REFERENCE_STRUCTURAL_FINGERPRINT_ENV, None)

        node_bodies: list[Mapping[str, object]] = []
        rebound_count = 0
        lane_peaks: dict[str, int] = {}
        merged_shards: list[dict[str, object]] = []
        lane_paths: list[tuple[str, str]] = []
        catalog_count = 0

        for index, asset_class in enumerate(_lane_local._candidate_lanes()):
            state = _run_lane_transaction(
                path,
                resolved_values,
                asset_class=asset_class.value,
                index=index,
                decision_epoch=decision_epoch,
            )
            lane_peaks[asset_class.value] = int(state.get("peak_rss_bytes") or 0)
            if state.get("dynamic") is not True:
                continue

            descriptor = _legacy._descriptor(state.get("blob"))
            merged_shards.append(
                {
                    "asset_class": asset_class.value,
                    "blob": _legacy._descriptor_dict(descriptor),
                    "record_count": int(state.get("record_count") or 0),
                }
            )
            catalog_count += int(state.get("record_count") or 0)
            publication_path = str(state.get("provider_preselection_path") or "")
            if publication_path:
                lane_paths.append((asset_class.value, publication_path))

            if state.get("scheduled") is not True:
                continue
            node = state.get("node")
            if not isinstance(node, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"transactional lane produced no node for {asset_class.value}"
                )
            node_bodies.append(dict(node))
            rebound_count += int(bool(state.get("compatibility_rebound")))

        if not node_bodies:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "transactional lane builder found no scheduled comprehensive-discovery lanes"
            )

        publication_index_path = path.parent / "lane-publication-index.json"
        _legacy._atomic_json(
            publication_index_path,
            {
                "schema_version": "lane-local-provider-publication-index.v1",
                "request_id": request.get("request_id"),
                "catalog_count": catalog_count,
                "lane_paths": [list(item) for item in lane_paths],
                **_legacy._authority_fields(),
            },
        )
        publication = _lane_local.LanePublicationIndex(
            path=str(publication_index_path),
            catalog_count=catalog_count,
            lane_paths=tuple(lane_paths),
        )
        publication_descriptor = _legacy._write_pickle_blob(
            path.parent,
            "finalizer-publication-index.pkl",
            publication,
        )
        request_policy = _legacy._descriptor(request.get("policy_blob"))
        material: dict[str, object] = {
            "schema_version": _legacy._SCHEMA,
            "request_id": str(request.get("request_id") or ""),
            "release": _legacy._release(resolved_values),
            "decision_epoch": str(request.get("decision_epoch") or ""),
            "policy_version": str(getattr(policy, "version", "")),
            "policy_blob": _legacy._descriptor_dict(request_policy),
            # Kept under the established manifest key for finalizer compatibility.  These
            # descriptors now point only to merged finalizer shards; raw catalog shards are
            # never persisted by the transactional runtime.
            "raw_catalog_shards": merged_shards,
            "publication_blob": _legacy._descriptor_dict(publication_descriptor),
            "lane_publications": [list(item) for item in lane_paths],
            "compatibility_rebound_count": rebound_count,
            "bounded_memory_builder": True,
            "lane_local_catalogs": True,
            "second_level_lane_memory_bound": True,
            "bounded_provider_publication": True,
            "transactional_lane_compaction": True,
            "raw_catalog_persisted": False,
            "builder_peak_rss_bytes": {"lanes": lane_peaks},
            "nodes": node_bodies,
            **_legacy._authority_fields(),
        }
        body = dict(material)
        body["manifest_id"] = _legacy._digest(material)
        manifest_path = _legacy._manifest_path(path)
        _legacy._atomic_json(manifest_path, body)
        try:
            (path.parent / "failure.json").unlink()
        except FileNotFoundError:
            pass
        return manifest_path
    except BaseException as error:  # noqa: BLE001 - fail closed with durable attribution.
        try:
            _legacy._write_failure(
                path,
                stage="transactional_lane_coordinator",
                error=error,
                values=resolved_values,
            )
        except BaseException:
            pass
        raise


def install_transactional_lane_comprehensive_discovery_coordinator() -> None:
    """Make end-to-end lane transactions authoritative for spool preparation."""

    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    spawn_safe.build_spool = build_spool


__all__ = [
    "build_spool",
    "install_transactional_lane_comprehensive_discovery_coordinator",
]
