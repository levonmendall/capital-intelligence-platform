"""Bound exact-epoch provider acquisition ahead of serialized comprehensive screening.

Comprehensive discovery historically performs provider acquisition and terminal screening
inside one end-to-end market-lane child and then advances to the next lane.  That is ideal
for memory isolation but it serializes independent network latency across every scheduled
market and repeatedly consumes the fixed evidence-freshness epoch before screening can
finish.

This module separates only that resource boundary.  On Render, scheduled market lanes may
pre-build their canonical provider-preselection publications in a small bounded set of
finite child interpreters.  Each child uses the same decision epoch, policy, structural
catalog identity, provider code, publication schema, and output path that the subsequent
canonical transaction uses.  The canonical transaction still runs one lane at a time and
must validate/reuse the publication before terminal screening, certification-node creation,
market-evidence qualification, and durable transaction completion.

The fan-out is acceleration only.  It has no evidence, candidate, sizing, construction,
execution, CIO, or real-money authority.  A child failure, timeout, partial file, cache miss,
or unsupported environment falls back to the unchanged serialized transaction.  A fixed
portion of the existing 900-second evidence epoch is always reserved for serialized
screening, paper evidence, and provider-free finalization; this module never extends or
resets the freshness deadline.
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


def _scheduled_lane_items(decision_epoch: datetime) -> tuple[tuple[int, CandidateAssetClass], ...]:
    """Return canonical lane indices for lanes scheduled in this exact decision epoch."""

    from operations import comprehensive_market_discovery as facade
    from operations import lane_local_comprehensive_discovery_spool as lane_local

    active = frozenset(facade._core._base.scheduled_discovery_lanes(decision_epoch))
    return tuple(
        (index, asset_class)
        for index, asset_class in enumerate(lane_local._candidate_lanes())
        if asset_class in active
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
    """Pre-acquire scheduled lane publications concurrently inside the existing epoch."""

    resolved = dict(values)
    if not _render_enabled(resolved):
        return {"attempted": False, "reason": "non_render", "completed": 0, "failed": 0}

    budget = _fanout_budget_seconds(decision_epoch, resolved)
    if budget <= 0.0:
        return {"attempted": False, "reason": "downstream_reserve", "completed": 0, "failed": 0}

    path = Path(request_path).expanduser()
    pending = list(_scheduled_lane_items(decision_epoch))
    if not pending:
        return {"attempted": False, "reason": "no_scheduled_lanes", "completed": 0, "failed": 0}

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
        "scheduled_lanes": len(_scheduled_lane_items(decision_epoch)),
        "completed": completed,
        "failed": failed,
        "timed_out": timed_out,
        "budget_seconds": round(budget, 3),
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
        json.dumps({"event": "epoch_scoped_provider_acquisition_fanout", **report}, sort_keys=True),
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
    """Build only one canonical provider publication; never perform terminal screening."""

    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import bounded_provider_preselection_publication as publication
    from operations import cached_transactional_comprehensive_discovery_lane as cached
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import comprehensive_market_discovery as facade
    from operations import transactional_comprehensive_discovery_lane as transaction

    path = Path(request_path).expanduser()
    request, policy = bounded._validate_request(path, values)
    timestamp = legacy._parse_timestamp(request.get("decision_epoch"), field_name="decision_epoch")
    asset_class = CandidateAssetClass(asset_class_value)

    cached.install_cached_structural_lane_loader()
    core = facade._core
    raw = transaction._load_catalog_records(
        core=core,
        values=values,
        policy=policy,
        timestamp=timestamp,
        asset_class=asset_class,
    )
    merged = transaction._bounded_lane._merge_certified_lane(
        core,
        raw,
        asset_class=asset_class,
        timestamp=timestamp,
    )
    del raw

    required = asset_class in core._base._DEFAULT_REQUIRED_DISCOVERY_LANES
    dynamic = bool(required or merged)
    scheduled = bool(dynamic and core._base._lane_is_scheduled(asset_class, timestamp))
    if not scheduled:
        return {
            "scheduled": False,
            "asset_class": asset_class.value,
            "record_count": len(merged),
            "publication_ready": False,
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
        raise RuntimeError(f"{asset_class.value} provider fanout publication count changed")
    return {
        "scheduled": True,
        "asset_class": asset_class.value,
        "record_count": len(merged),
        "publication_ready": True,
        "reused": bool(getattr(result, "reused", False)),
    }


def install_epoch_scoped_provider_acquisition() -> None:
    """Wrap the canonical spool builder with bounded provider-I/O fan-out on Render."""

    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    current = spawn_safe.build_spool
    if getattr(current, "_epoch_scoped_provider_acquisition", False):
        return

    def build_spool(request_path: str | Path, *, values: Mapping[str, str] | None = None):
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
            except Exception as error:
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
    except BaseException as error:
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
