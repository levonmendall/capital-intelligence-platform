"""Bound exact-epoch provider acquisition ahead of serialized comprehensive screening.

Comprehensive discovery historically performs provider acquisition and terminal screening
inside one end-to-end market-lane child and then advances to the next lane. That is ideal
for memory isolation but it serializes independent network latency across every scheduled
market and repeatedly consumes the fixed evidence-freshness epoch before screening can
finish.

This module separates only that resource boundary. On Render, scheduled market lanes whose
release/reference-bound structural catalogs are already present may pre-build their
canonical provider-preselection publications in a small bounded set of finite child
interpreters. Each child uses the same decision epoch, policy, structural catalog identity,
provider implementation, publication schema, and output path that the subsequent canonical
transaction uses. The canonical transaction still runs one lane at a time and must
validate/reuse the publication before terminal screening, certification-node creation,
market-evidence qualification, and durable transaction completion.

The fan-out is provider-I/O acceleration only. It is forbidden from reconstructing a
missing structural catalog in parallel: a cache miss exits the advisory child and leaves
that lane to the unchanged serialized transaction. The fan-out has no evidence, candidate,
sizing, construction, execution, CIO, or real-money authority. A child failure, timeout,
partial file, cache miss, or unsupported environment falls back to the unchanged serialized
transaction. A fixed portion of the existing evidence epoch is always reserved for
serialized screening, paper evidence, and provider-free finalization; this module never
extends or resets the freshness deadline.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
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
_DEFAULT_WORKERS = 3
_MAX_WORKERS = 4
_MAX_FANOUT_SECONDS = 300.0
_DOWNSTREAM_RESERVE_SECONDS = 480.0
_TERMINATION_GRACE_SECONDS = 1.0
_WORKERS_ENV = "CAPITAL_INTELLIGENCE_PROVIDER_ACQUISITION_WORKERS"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _render_enabled(values: Mapping[str, str]) -> bool:
    return str(values.get("RENDER") or "").strip().lower() == "true"


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


def _signal_process_tree(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, sig)
            return
        except (OSError, ProcessLookupError):
            pass
    try:
        if sig == signal.SIGKILL:
            process.kill()
        else:
            process.terminate()
    except OSError:
        pass


def _terminate_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    _signal_process_tree(process, signal.SIGTERM)
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    _signal_process_tree(process, signal.SIGKILL)
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


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
    """Pre-acquire cached-structure lane publications inside the existing epoch."""

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
    pending = list(lane_items)
    if not pending:
        return {
            "attempted": False,
            "reason": "no_cacheable_scheduled_lanes",
            "completed": 0,
            "failed": 0,
        }

    workers = _worker_count(resolved)
    active: dict[int, tuple[subprocess.Popen[bytes], CandidateAssetClass]] = {}
    completed = 0
    failed = 0
    timed_out = 0
    maximum_parallel = 0
    deadline = time.monotonic() + budget

    try:
        while pending or active:
            while pending and len(active) < workers and time.monotonic() < deadline:
                index, asset_class = pending.pop(0)
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
                        start_new_session=(os.name == "posix"),
                    )
                except (OSError, ValueError):
                    failed += 1
                    continue
                active[index] = (process, asset_class)
                maximum_parallel = max(maximum_parallel, len(active))

            progressed = False
            for index, (process, _asset_class) in tuple(active.items()):
                return_code = process.poll()
                if return_code is None:
                    continue
                active.pop(index, None)
                progressed = True
                if int(return_code) == 0:
                    completed += 1
                else:
                    failed += 1

            if not pending and not active:
                break
            if time.monotonic() >= deadline:
                timed_out += len(active)
                failed += len(active)
                for process, _asset_class in tuple(active.values()):
                    _terminate_and_reap(process)
                active.clear()
                break
            if not progressed:
                time.sleep(0.02)
    finally:
        for process, _asset_class in tuple(active.values()):
            _terminate_and_reap(process)

    report = {
        "attempted": True,
        "worker_limit": workers,
        "maximum_parallel": maximum_parallel,
        "scheduled_lanes": len(lane_items),
        "completed": completed,
        "failed": failed,
        "timed_out": timed_out,
        "budget_seconds": round(budget, 3),
        "structural_reconstruction_parallelized": False,
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


def prepare_lane_provider_publication(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    asset_class_value: str,
    index: int,
) -> Mapping[str, object]:
    """Build one provider publication from verified prewarmed structure only."""

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

    publication_path = transaction._publication_path(
        path.parent,
        asset_class=asset_class.value,
        index=index,
    )
    lane_policy = replace(policy, provider_preselection_path=str(publication_path))
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
    return {
        "scheduled": True,
        "asset_class": asset_class.value,
        "record_count": len(merged),
        "publication_ready": True,
        "reused": bool(getattr(result, "reused", False)),
        "structural_reconstruction_parallelized": False,
    }


def install_epoch_scoped_provider_acquisition() -> None:
    """Wrap the canonical spool builder with bounded provider-I/O fan-out on Render."""

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
                run_provider_acquisition_fanout(
                    path,
                    values=resolved,
                    decision_epoch=epoch,
                )
            except Exception as error:  # noqa: BLE001 - serial path remains authority.
                print(
                    json.dumps(
                        {
                            "event": "epoch_scoped_provider_acquisition_fanout_unavailable",
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
                    flush=True,
                )
        return current(request_path, values=resolved)

    build_spool._epoch_scoped_provider_acquisition = True  # type: ignore[attr-defined]
    build_spool._canonical_serial_builder = current  # type: ignore[attr-defined]
    spawn_safe.build_spool = build_spool


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--asset-class", required=True)
    parser.add_argument("--index", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        prepare_lane_provider_publication(
            args.request,
            values=dict(os.environ),
            asset_class_value=str(args.asset_class),
            index=int(args.index),
        )
    except BaseException as error:  # noqa: BLE001 - advisory child reports type only.
        print(
            json.dumps(
                {
                    "event": "epoch_scoped_provider_acquisition_lane_failed",
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
    "run_provider_acquisition_fanout",
]
