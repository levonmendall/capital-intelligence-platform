"""Bound exact-epoch provider acquisition ahead of serialized comprehensive screening.

Comprehensive discovery historically performs structural reconstruction, provider
acquisition, and terminal screening inside one end-to-end market-lane child and then
advances to the next lane. That is ideal for memory isolation but it serializes independent
network latency across every scheduled market and can consume the fixed evidence-freshness
epoch before screening can finish.

This module separates only the provider-I/O resource boundary. On Render it prepares
release/reference-bound structural catalogs serially in finite child interpreters and hands
each verified catalog directly to a small bounded fan-out. Provider I/O for an early ready
lane may therefore run while the next single structural child prepares, without ever
running two structural reconstructions together. The canonical transaction still runs one
lane at a time and must validate/reuse the structural cache and publication before terminal
screening, certification-node creation, market-evidence qualification, and durable
transaction completion.

Structural preparation is deliberately serial and provider-free. It reuses the exact
canonical governed catalog loader and certified merge seam, persists only the existing
structural-only cache schema, and never performs provider preselection or terminal
screening. This makes the acceleration usable on the first evidence attempt of a newly
deployed release without recreating the parallel structural-memory pressure that the
transactional lane design removed.

The early fan-out remains provider-I/O acceleration only. Provider output is written to a
staging path and is atomically promoted to the canonical lane path only when the provider
runtime reports no limitations. A throttled, partial, or otherwise limited result is
removed. When the later comprehensive spool builder re-enters this wrapper it validates
every scheduled cacheable lane directly in reuse-only mode: clean exact-request
publications may be reused, but a missing or invalid publication cannot trigger a second
provider-network acquisition and the serialized transaction cannot begin on a partial set.
The serialized transactional lane independently enforces the same reuse-only contract.

Neither structural preparation nor provider fan-out has evidence, candidate, sizing,
construction, execution, CIO, or real-money authority. A child failure, timeout, partial
file, cache miss, or unsupported environment remains fail-closed at the canonical evidence
boundary. All acceleration children remain in the outer evidence stage's process group, so
the existing resource/freshness supervisor can terminate the complete active tree
fail-closed. Both phases share one fixed portion of the existing evidence epoch; a hard
reserve remains for serialized screening, paper evidence, and provider-free finalization.
This module never extends or resets the freshness deadline.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from cio import CandidateAssetClass


_MODULE = "operations.epoch_scoped_provider_acquisition"
_DEFAULT_WORKERS = 6
_MAX_WORKERS = 6
_MAX_FANOUT_SECONDS = 300.0
_DOWNSTREAM_RESERVE_SECONDS = 480.0
_TERMINATION_GRACE_SECONDS = 1.0
_WORKERS_ENV = "CAPITAL_INTELLIGENCE_PROVIDER_ACQUISITION_WORKERS"
_REUSE_ONLY_ENV = "CAPITAL_INTELLIGENCE_PROVIDER_ACQUISITION_REUSE_ONLY"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _render_enabled(values: Mapping[str, str]) -> bool:
    return str(values.get("RENDER") or "").strip().lower() == "true"


def _reuse_only(values: Mapping[str, str]) -> bool:
    return str(values.get(_REUSE_ONLY_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def _worker_count(values: Mapping[str, str]) -> int:
    raw = str(values.get(_WORKERS_ENV) or "").strip()
    try:
        requested = _DEFAULT_WORKERS if not raw else int(raw)
    except ValueError:
        requested = _DEFAULT_WORKERS
    return max(1, min(_MAX_WORKERS, requested))


def _fanout_budget_seconds(
    decision_epoch: datetime,
    values: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> float:
    """Use only spare epoch time and preserve a hard downstream reserve."""

    from operations.continuous_evidence_plane import _max_age_seconds

    epoch = _aware(decision_epoch, field_name="decision_epoch")
    current = _aware(now or datetime.now(timezone.utc), field_name="provider_fanout_now")
    max_age = float(_max_age_seconds(values))
    remaining = (epoch + timedelta(seconds=max_age) - current).total_seconds()
    reserve = min(_DOWNSTREAM_RESERVE_SECONDS, max_age * 0.60)
    spare = remaining - reserve
    if spare <= 0.0:
        return 0.0
    return max(0.0, min(_MAX_FANOUT_SECONDS, spare))


def _scheduled_lane_items(
    decision_epoch: datetime,
) -> tuple[tuple[int, CandidateAssetClass], ...]:
    """Return canonical indices for cacheable lanes scheduled in this exact epoch."""

    from operations import comprehensive_market_discovery as facade
    from operations import lane_local_comprehensive_discovery_spool as lane_local

    active = frozenset(facade._core._base.scheduled_discovery_lanes(decision_epoch))
    return tuple(
        (index, asset_class)
        for index, asset_class in enumerate(lane_local._candidate_lanes())
        if asset_class in active and asset_class is not CandidateAssetClass.OPTION
    )


def _terminate_and_reap(process: subprocess.Popen[bytes]) -> None:
    """Stop one advisory child without escaping the outer process-group supervisor."""

    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
    except OSError:
        return
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _structural_command(
    *,
    request_path: Path,
    asset_class: CandidateAssetClass,
    index: int,
) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        _MODULE,
        "--prepare-structure",
        "--request",
        str(request_path),
        "--asset-class",
        asset_class.value,
        "--index",
        str(index),
    )


def _publication_command(
    *,
    request_path: Path,
    asset_class: CandidateAssetClass,
    index: int,
) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        _MODULE,
        "--request",
        str(request_path),
        "--asset-class",
        asset_class.value,
        "--index",
        str(index),
    )


def run_provider_acquisition_fanout(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    decision_epoch: datetime,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> Mapping[str, object]:
    """Pipeline provider I/O behind strictly serial structure inside one epoch budget."""

    resolved = dict(values)
    if not _render_enabled(resolved):
        return {"attempted": False, "reason": "non_render", "completed": 0, "failed": 0}

    budget = _fanout_budget_seconds(decision_epoch, resolved)
    if budget <= 0.0:
        return {
            "attempted": False,
            "reason": "downstream_reserve",
            "completed": 0,
            "failed": 0,
        }

    path = Path(request_path).expanduser()
    lane_items = _scheduled_lane_items(decision_epoch)
    if not lane_items:
        return {
            "attempted": False,
            "reason": "no_cacheable_scheduled_lanes",
            "completed": 0,
            "failed": 0,
        }

    acceleration_started = time.monotonic()
    deadline = acceleration_started + budget
    workers = _worker_count(resolved)
    pending: list[tuple[int, CandidateAssetClass]] = []
    active: dict[int, tuple[subprocess.Popen[bytes], CandidateAssetClass]] = {}
    structural_attempted = 0
    structural_completed = 0
    structural_failed = 0
    structural_timed_out = 0
    structural_elapsed_seconds = 0.0
    structural_active = 0
    maximum_structural_concurrency = 0
    provider_attempted = 0
    provider_completed = 0
    provider_failed = 0
    provider_timed_out = 0
    maximum_provider_concurrency = 0
    provider_activity_overlapped_structure = False
    provider_structural_overlap_events = 0

    def reap_provider_children() -> bool:
        nonlocal provider_completed, provider_failed
        progressed = False
        for index, (process, _asset_class) in tuple(active.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            active.pop(index, None)
            progressed = True
            if int(return_code) == 0:
                provider_completed += 1
            else:
                provider_failed += 1
        return progressed

    def launch_ready_provider_children() -> None:
        nonlocal provider_attempted, provider_failed, maximum_provider_concurrency
        while pending and len(active) < workers and time.monotonic() < deadline:
            index, asset_class = pending.pop(0)
            provider_attempted += 1
            try:
                process = popen(
                    _publication_command(
                        request_path=path,
                        asset_class=asset_class,
                        index=index,
                    ),
                    cwd=str(Path(__file__).resolve().parents[1]),
                    env=resolved,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    # Keep every fan-out child subordinate to the existing outer stage
                    # resource/freshness process-group kill boundary.
                    start_new_session=False,
                )
            except (OSError, ValueError):
                provider_failed += 1
                continue
            active[index] = (process, asset_class)
            maximum_provider_concurrency = max(maximum_provider_concurrency, len(active))

    try:
        # This loop is the structural semaphore: it waits for the one current structural
        # child before it can create the next. Provider children are launched immediately
        # after each verified structural result and remain free to run during that wait.
        for index, asset_class in lane_items:
            reap_provider_children()
            launch_ready_provider_children()
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                break

            structural_attempted += 1
            structural_started = time.monotonic()
            try:
                process = popen(
                    _structural_command(
                        request_path=path,
                        asset_class=asset_class,
                        index=index,
                    ),
                    cwd=str(Path(__file__).resolve().parents[1]),
                    env=dict(resolved),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    # Structural reconstruction is intentionally serial. Keep the child
                    # in the outer evidence process group so freshness/resource
                    # supervision can still terminate the complete tree fail-closed.
                    start_new_session=False,
                )
            except (OSError, ValueError):
                structural_failed += 1
                structural_elapsed_seconds += max(0.0, time.monotonic() - structural_started)
                continue

            structural_active += 1
            maximum_structural_concurrency = max(
                maximum_structural_concurrency, structural_active
            )
            if active:
                provider_activity_overlapped_structure = True
                provider_structural_overlap_events += 1

            try:
                return_code = int(process.wait(timeout=max(0.001, remaining)))
            except subprocess.TimeoutExpired:
                structural_timed_out += 1
                structural_failed += 1
                _terminate_and_reap(process)
                structural_active -= 1
                structural_elapsed_seconds += max(0.0, time.monotonic() - structural_started)
                break
            except OSError:
                structural_failed += 1
                _terminate_and_reap(process)
                structural_active -= 1
                structural_elapsed_seconds += max(0.0, time.monotonic() - structural_started)
                continue

            structural_active -= 1
            structural_elapsed_seconds += max(0.0, time.monotonic() - structural_started)
            if return_code == 0:
                structural_completed += 1
                pending.append((index, asset_class))
                reap_provider_children()
                launch_ready_provider_children()
            else:
                structural_failed += 1

        while pending or active:
            if time.monotonic() >= deadline:
                provider_timed_out += len(active)
                provider_failed += len(active)
                for process, _asset_class in tuple(active.values()):
                    _terminate_and_reap(process)
                active.clear()
                break
            progressed = reap_provider_children()
            launch_ready_provider_children()
            if not pending and not active:
                break
            if not progressed:
                time.sleep(0.02)
    finally:
        for process, _asset_class in tuple(active.values()):
            _terminate_and_reap(process)

    acceleration_elapsed_seconds = max(0.0, time.monotonic() - acceleration_started)
    structural_skipped = max(0, len(lane_items) - structural_attempted)
    provider_skipped = max(0, len(lane_items) - provider_attempted)

    report = {
        "attempted": True,
        "reuse_only": _reuse_only(resolved),
        "worker_limit": workers,
        "maximum_parallel": maximum_provider_concurrency,
        "scheduled_lanes": len(lane_items),
        "provider_attempted_lanes": provider_attempted,
        "provider_completed_lanes": provider_completed,
        "provider_skipped_lanes": provider_skipped,
        "provider_skipped_budget": max(0, structural_completed - provider_attempted),
        "completed": provider_completed,
        "failed": provider_failed,
        "timed_out": provider_timed_out,
        "structural_prewarm_attempted": structural_attempted,
        "structural_prewarm_completed": structural_completed,
        "structural_prewarm_failed": structural_failed,
        "structural_prewarm_timed_out": structural_timed_out,
        "structural_prewarm_skipped_budget": structural_skipped,
        "structural_prewarm_maximum_parallel": maximum_structural_concurrency,
        "structural_lanes_attempted": structural_attempted,
        "structural_lanes_completed": structural_completed,
        "structural_lanes_skipped": structural_skipped,
        "provider_lanes_attempted": provider_attempted,
        "provider_lanes_completed": provider_completed,
        "provider_lanes_skipped": provider_skipped,
        "structural_elapsed_seconds": round(structural_elapsed_seconds, 3),
        "provider_activity_overlapped_structure": provider_activity_overlapped_structure,
        "provider_structural_overlap_events": provider_structural_overlap_events,
        "maximum_structural_concurrency": maximum_structural_concurrency,
        "maximum_provider_concurrency": maximum_provider_concurrency,
        "acceleration_elapsed_seconds": round(acceleration_elapsed_seconds, 3),
        "budget_seconds": round(budget, 3),
        "structural_reconstruction_parallelized": False,
        "limited_publication_promoted": False,
        "outer_process_group_inherited": True,
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
    print(
        json.dumps(
            {"event": "epoch_scoped_provider_acquisition_fanout", **report},
            sort_keys=True,
        ),
        flush=True,
    )
    return report


def prepare_lane_structural_catalog(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    asset_class_value: str,
    index: int,
) -> Mapping[str, object]:
    """Prepare one structural-only cache entry through the canonical governed merge seam."""

    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import comprehensive_market_discovery as facade
    from operations import transactional_comprehensive_discovery_lane as transaction

    path = Path(request_path).expanduser()
    resolved = dict(values)
    request, policy = bounded._validate_request(path, resolved)
    timestamp = legacy._parse_timestamp(
        request.get("decision_epoch"), field_name="decision_epoch"
    )
    asset_class = CandidateAssetClass(asset_class_value)
    if asset_class is CandidateAssetClass.OPTION:
        raise RuntimeError("structural prewarm refuses timestamp-constructed option catalogs")

    core = facade._core
    if asset_class not in core._base.scheduled_discovery_lanes(timestamp):
        return {
            "scheduled": False,
            "asset_class": asset_class.value,
            "structural_ready": False,
            "reused": False,
            "provider_preselection_performed": False,
            "terminal_screening_performed": False,
        }

    policy_version = str(getattr(policy, "version", ""))
    structural.bind_reference_structural_fingerprint(resolved)
    cached = structural.load_structural_catalog(
        resolved,
        asset_class=asset_class,
        policy_version=policy_version,
        requested_as_of=timestamp,
    )
    if cached is not None:
        return {
            "scheduled": True,
            "asset_class": asset_class.value,
            "record_count": len(cached.records),
            "raw_record_count": cached.raw_record_count,
            "structural_ready": True,
            "reused": True,
            "provider_preselection_performed": False,
            "terminal_screening_performed": False,
        }

    raw = transaction._load_catalog_records(
        core=core,
        values=resolved,
        policy=policy,
        timestamp=timestamp,
        asset_class=asset_class,
    )
    raw_record_count = len(raw)
    merged = transaction._bounded_lane._merge_certified_lane(
        core,
        raw,
        asset_class=asset_class,
        timestamp=timestamp,
    )
    del raw

    if not structural.publish_structural_catalog(
        resolved,
        asset_class=asset_class,
        policy_version=policy_version,
        source_as_of=timestamp,
        raw_record_count=raw_record_count,
        records=merged,
    ):
        raise RuntimeError(
            f"structural prewarm could not persist cache; asset_class={asset_class.value}"
        )
    verified = structural.load_structural_catalog(
        resolved,
        asset_class=asset_class,
        policy_version=policy_version,
        requested_as_of=timestamp,
    )
    if verified is None:
        raise RuntimeError(
            f"structural prewarm cache did not verify; asset_class={asset_class.value}"
        )
    if verified.raw_record_count != raw_record_count or len(verified.records) != len(merged):
        raise RuntimeError(
            f"structural prewarm cache identity changed; asset_class={asset_class.value}"
        )

    return {
        "scheduled": True,
        "asset_class": asset_class.value,
        "record_count": len(merged),
        "raw_record_count": raw_record_count,
        "structural_ready": True,
        "reused": False,
        "provider_preselection_performed": False,
        "terminal_screening_performed": False,
        "structural_reconstruction_parallelized": False,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _remove_staging_publication(path: Path) -> None:
    for candidate in (path, path.with_suffix(path.suffix + ".tmp")):
        try:
            if candidate.is_symlink():
                continue
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _existing_clean_publication(publication, catalogs, *, as_of, policy):
    """Return one exact compatible canonical publication without invoking a provider."""

    try:
        records = publication._records_for_lane(catalogs)
    except (RuntimeError, TypeError, ValueError):
        # Reuse validation is an optimization for the early acquisition owner. Malformed
        # synthetic/pre-validation input means only that no reusable artifact can be
        # established here. Reuse-only comprehensive mode still fails closed below, while
        # the early owner delegates validation to its unchanged canonical publication call.
        return None
    if not records:
        return None
    timestamp = publication._core._aware(as_of, field_name="as_of")
    fingerprint = publication._streaming_catalog_fingerprint(records)
    path = publication._core._publication_path(policy)
    freshness_days = int(getattr(policy, "preselection_freshness_days", 3))
    existing = publication._existing_result_bounded(
        path,
        as_of=timestamp,
        fingerprint=fingerprint,
        catalog_count=len(records),
        freshness_days=freshness_days,
    )
    if existing is None:
        return None
    limitations = tuple(
        str(item)
        for item in getattr(existing, "limitations", ())
        if str(item).strip()
    )
    if limitations:
        return None
    return existing


def prepare_lane_provider_publication(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    asset_class_value: str,
    index: int,
) -> Mapping[str, object]:
    """Build or reuse one clean provider publication from verified structure only."""

    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import bounded_provider_preselection_publication as publication
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import comprehensive_market_discovery as facade
    from operations import transactional_comprehensive_discovery_lane as transaction

    path = Path(request_path).expanduser()
    resolved = dict(values)
    request, policy = bounded._validate_request(path, resolved)
    timestamp = legacy._parse_timestamp(
        request.get("decision_epoch"), field_name="decision_epoch"
    )
    asset_class = CandidateAssetClass(asset_class_value)
    if asset_class is CandidateAssetClass.OPTION:
        raise RuntimeError("provider fanout refuses timestamp-constructed option catalogs")

    core = facade._core
    policy_version = str(getattr(policy, "version", ""))
    structural.bind_reference_structural_fingerprint(resolved)
    cached = structural.load_structural_catalog(
        resolved,
        asset_class=asset_class,
        policy_version=policy_version,
        requested_as_of=timestamp,
    )
    if cached is None:
        raise RuntimeError(
            f"provider fanout requires prewarmed structural cache; asset_class={asset_class.value}"
        )
    source_active = asset_class in core._base.scheduled_discovery_lanes(cached.source_as_of)
    requested_active = asset_class in core._base.scheduled_discovery_lanes(timestamp)
    if source_active is not requested_active:
        raise RuntimeError(
            f"provider fanout structural schedule changed; asset_class={asset_class.value}"
        )
    merged = cached.records

    required = asset_class in core._base._DEFAULT_REQUIRED_DISCOVERY_LANES
    dynamic = bool(required or merged)
    scheduled = bool(dynamic and core._base._lane_is_scheduled(asset_class, timestamp))
    if not scheduled:
        return {
            "scheduled": False,
            "asset_class": asset_class.value,
            "record_count": len(merged),
            "publication_ready": False,
            "structural_reconstruction_parallelized": False,
        }

    canonical_path = transaction._publication_path(
        path.parent,
        asset_class=asset_class.value,
        index=index,
    )
    canonical_policy = replace(policy, provider_preselection_path=str(canonical_path))
    existing = _existing_clean_publication(
        publication,
        {asset_class: merged},
        as_of=timestamp,
        policy=canonical_policy,
    )
    if existing is not None:
        return {
            "scheduled": True,
            "asset_class": asset_class.value,
            "record_count": len(merged),
            "publication_ready": True,
            "reused": True,
            "structural_reconstruction_parallelized": False,
            "limited_publication_promoted": False,
        }
    if _reuse_only(resolved):
        raise RuntimeError(
            f"{asset_class.value} exact-epoch provider publication is unavailable; "
            "reuse-only comprehensive fanout refuses provider reacquisition"
        )

    staging_path = canonical_path.with_name(canonical_path.name + ".fanout")
    _remove_staging_publication(staging_path)
    lane_policy = replace(policy, provider_preselection_path=str(staging_path))
    promoted = False
    try:
        result = publication.ensure_provider_preselection_publication(
            {asset_class: merged},
            as_of=timestamp,
            policy=lane_policy,
            market_probe=core.default_provider_preselection_market_probe,
        )
        if int(getattr(result, "catalog_count", -1)) != len(merged):
            raise RuntimeError(
                f"{asset_class.value} provider fanout publication count changed"
            )
        if (
            Path(result.path) != staging_path
            or not staging_path.is_file()
            or staging_path.is_symlink()
        ):
            raise RuntimeError(
                f"{asset_class.value} provider fanout did not publish the expected staging file"
            )
        limitations = tuple(
            str(item)
            for item in getattr(result, "limitations", ())
            if str(item)
        )
        if limitations:
            raise RuntimeError(
                f"{asset_class.value} provider fanout produced limited evidence"
            )
        staging_path.replace(canonical_path)
        promoted = True
        publication.verify_provider_preselection_artifact(
            canonical_path,
            as_of=timestamp,
            fingerprint=publication.provider_preselection_catalog_fingerprint(
                {asset_class: merged}
            ),
            catalog_count=int(result.catalog_count),
            signal_count=int(result.signal_count),
            available_at=result.available_at,
            freshness_days=int(getattr(policy, "preselection_freshness_days", 3)),
        )
    except BaseException:
        _remove_staging_publication(staging_path)
        if promoted:
            _remove_staging_publication(canonical_path)
        raise

    return {
        "scheduled": True,
        "asset_class": asset_class.value,
        "record_count": len(merged),
        "publication_ready": True,
        "reused": False,
        "structural_reconstruction_parallelized": False,
        "limited_publication_promoted": False,
    }


def install_epoch_scoped_provider_acquisition() -> None:
    """Wrap canonical spooling with exact-epoch publication validation on Render."""

    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    current = spawn_safe.build_spool
    if getattr(current, "_epoch_scoped_provider_acquisition", False):
        return

    def build_spool(
        request_path: str | Path,
        *,
        values: Mapping[str, str] | None = None,
    ):
        resolved = dict(os.environ if values is None else values)
        if _render_enabled(resolved):
            path = Path(request_path).expanduser()
            try:
                request, _policy = bounded._validate_request(path, resolved)
                epoch = legacy._parse_timestamp(
                    request.get("decision_epoch"), field_name="decision_epoch"
                )
                reuse_only_values = dict(resolved)
                reuse_only_values[_REUSE_ONLY_ENV] = "true"
                for index, asset_class in _scheduled_lane_items(epoch):
                    prepare_lane_provider_publication(
                        path,
                        values=reuse_only_values,
                        asset_class_value=asset_class.value,
                        index=index,
                    )
            except Exception as error:  # noqa: BLE001 - handoff must terminate fail-closed.
                print(
                    json.dumps(
                        {
                            "event": "epoch_scoped_provider_publication_handoff_failed",
                            "error_type": type(error).__name__,
                            "error_detail": str(error)[:1200],
                            "reuse_only": True,
                            "advisory_only": False,
                            "evidence_certified": False,
                            "decision_authority": False,
                            "candidate_authority": False,
                            "sizing_authority": False,
                            "construction_authority": False,
                            "execution_authority": False,
                            "paper_only": True,
                            "real_money_authorized": False,
                            "credential_safe": True,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                raise
        return current(request_path, values=resolved)

    build_spool._epoch_scoped_provider_acquisition = True  # type: ignore[attr-defined]
    build_spool._canonical_serial_builder = current  # type: ignore[attr-defined]
    spawn_safe.build_spool = build_spool


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-structure", action="store_true")
    parser.add_argument("--request", required=True)
    parser.add_argument("--asset-class", required=True)
    parser.add_argument("--index", required=True, type=int)
    args = parser.parse_args(argv)
    values = dict(os.environ)
    try:
        if args.prepare_structure:
            prepare_lane_structural_catalog(
                args.request,
                values=values,
                asset_class_value=str(args.asset_class),
                index=int(args.index),
            )
        else:
            try:
                from operations.evidence_preparation_progress import (
                    install_post_public_provider_progress,
                )

                install_post_public_provider_progress(values)
            except Exception:  # noqa: BLE001 - supervision remains fail-closed without it.
                pass
            prepare_lane_provider_publication(
                args.request,
                values=values,
                asset_class_value=str(args.asset_class),
                index=int(args.index),
            )
    except BaseException as error:  # noqa: BLE001 - advisory child reports type only.
        print(
            json.dumps(
                {
                    "event": (
                        "epoch_scoped_provider_structural_prewarm_failed"
                        if args.prepare_structure
                        else "epoch_scoped_provider_acquisition_lane_failed"
                    ),
                    "asset_class": str(args.asset_class),
                    "index": int(args.index),
                    "error_type": type(error).__name__,
                    "advisory_only": True,
                    "evidence_certified": False,
                    "decision_authority": False,
                    "execution_authority": False,
                    "paper_only": True,
                    "real_money_authorized": False,
                    "credential_safe": True,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "install_epoch_scoped_provider_acquisition",
    "prepare_lane_provider_publication",
    "prepare_lane_structural_catalog",
    "run_provider_acquisition_fanout",
]
