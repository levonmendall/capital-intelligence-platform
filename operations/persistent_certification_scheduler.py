"""Persistent, provider-aware certification scheduling for all-market discovery.

This module is operational only. It does not change catalog membership, screening,
ranking, thresholds, CIO authority, portfolio construction, execution behavior, or
paper-only controls.

The scheduler turns the expensive deep-market-evidence portion of comprehensive
discovery into durable exact-release/epoch work nodes. Independent scheduled lanes are
prewarmed concurrently, provider families are protected by shared bounded leases, and
successful nodes are persisted immediately so a later lane/provider failure does not
force qualified work to repeat. The unchanged comprehensive-discovery implementation
remains the final terminal-accounting and global certification authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = "persistent-certification-dag.v1"
_NODE_SCHEMA_VERSION = "persistent-certification-node.v1"
_MANIFEST_SCHEMA_VERSION = "persistent-certification-manifest.v1"
_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"
_ENABLED_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_ENABLED"
_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"
_DEFAULT_WORKERS = 3
_MAX_WORKERS = 6
_DEFAULT_MARKET_NODE_VALID_SECONDS = 900.0
_FAILURE_MESSAGE_LIMIT = 1600

_PROVIDER_DEFAULT_CAPACITIES: Mapping[str, int] = {
    "alpaca": 2,
    "cme": 1,
    "coinbase": 2,
    "eodhd": 1,
    "kraken": 2,
    "massive": 1,
    "tradier": 1,
    "twelve": 2,
    "generic": 1,
}


class CertificationSchedulerError(RuntimeError):
    """Raised when required certification work cannot converge fail-closed."""


@dataclass(frozen=True, slots=True)
class CertificationNode:
    node_id: str
    asset_class: str
    provider_groups: tuple[str, ...]
    input_fingerprint: str
    deadline: datetime
    decision_eligible_count: int
    priority: int = 0
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CertificationNodeResult:
    node_id: str
    status: str
    reused: bool
    evidence_complete_count: int
    completed_at: datetime | None
    retry_after: datetime | None = None
    failure_type: str | None = None
    failure_message: str | None = None
    failure_cause_type: str | None = None
    failure_cause_message: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class CertificationRunResult:
    manifest_id: str
    required_nodes: tuple[str, ...]
    completed_nodes: tuple[str, ...]
    reused_nodes: tuple[str, ...]
    failed_nodes: tuple[str, ...]
    path: Path


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_failure_text(value: object) -> str | None:
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= _FAILURE_MESSAGE_LIMIT:
        return text
    return text[: _FAILURE_MESSAGE_LIMIT - 3] + "..."


def _failure_cause(error: BaseException) -> BaseException | None:
    if error.__cause__ is not None:
        return error.__cause__
    if not error.__suppress_context__:
        return error.__context__
    return None


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _enabled(values: Mapping[str, str]) -> bool:
    raw = str(values.get(_ENABLED_ENV) or "").strip().lower()
    if raw:
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{_ENABLED_ENV} is invalid")
    preparing = str(values.get(_PREPARING_ENV) or "").strip().lower()
    return (
        preparing in {"1", "true", "yes", "on"}
        and bool(values.get("CAPITAL_INTELLIGENCE_DATA_DIR"))
        and _release(values) != "unknown"
    )


def _worker_count(values: Mapping[str, str], node_count: int) -> int:
    raw = str(values.get(_WORKERS_ENV) or "").strip()
    requested = _DEFAULT_WORKERS
    if raw:
        try:
            requested = int(raw)
        except ValueError as error:
            raise ValueError(f"{_WORKERS_ENV} must be an integer") from error
    if requested < 1 or requested > _MAX_WORKERS:
        raise ValueError(f"{_WORKERS_ENV} must be between 1 and {_MAX_WORKERS}")
    return min(requested, max(1, node_count))


def _provider_capacity(values: Mapping[str, str], provider: str) -> int:
    token = "".join(character if character.isalnum() else "_" for character in provider.upper())
    env_name = f"CAPITAL_INTELLIGENCE_CERTIFICATION_PROVIDER_{token}_CAPACITY"
    raw = str(values.get(env_name) or "").strip()
    requested = _PROVIDER_DEFAULT_CAPACITIES.get(provider, 1)
    if raw:
        try:
            requested = int(raw)
        except ValueError as error:
            raise ValueError(f"{env_name} must be an integer") from error
    if requested < 1 or requested > 8:
        raise ValueError(f"{env_name} must be between 1 and 8")
    return requested


def _root(values: Mapping[str, str]) -> Path:
    return Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser() / "certification-dag"


def _epoch_key(epoch: datetime) -> str:
    return _aware(epoch, field_name="certification_epoch").strftime("%Y%m%dT%H%M%S%fZ")


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise CertificationSchedulerError(
                f"immutable certification scheduler artifact collision at {path}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_text(encoded, encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != encoded:
            raise CertificationSchedulerError(
                f"immutable certification scheduler artifact collision at {path}"
            )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class ProviderBudgetRegistry:
    """Non-blocking shared leases so ready work can use unrelated provider capacity."""

    def __init__(self, values: Mapping[str, str], providers: Sequence[str]) -> None:
        normalized = tuple(sorted({str(item).strip().lower() for item in providers if str(item).strip()}))
        self._locks = {
            provider: threading.BoundedSemaphore(_provider_capacity(values, provider))
            for provider in normalized
        }

    def try_acquire(self, providers: Sequence[str]) -> tuple[str, ...] | None:
        requested = tuple(sorted({str(item).strip().lower() for item in providers if str(item).strip()}))
        acquired: list[str] = []
        for provider in requested:
            semaphore = self._locks.setdefault(provider, threading.BoundedSemaphore(1))
            if not semaphore.acquire(blocking=False):
                for held in reversed(acquired):
                    self._locks[held].release()
                return None
            acquired.append(provider)
        return tuple(acquired)

    def release(self, lease: Sequence[str]) -> None:
        for provider in reversed(tuple(lease)):
            self._locks[provider].release()


class PersistentCertificationScheduler:
    """Persist exact-epoch node success and schedule only dependency-ready work."""

    def __init__(
        self,
        *,
        values: Mapping[str, str],
        release_sha: str,
        epoch: datetime,
        policy_version: str,
    ) -> None:
        self.values = values
        self.release_sha = str(release_sha).strip()
        self.epoch = _aware(epoch, field_name="scheduler_epoch")
        self.policy_version = str(policy_version)
        if not self.release_sha or self.release_sha == "unknown":
            raise ValueError("scheduler release_sha must be known")

    def _node_path(self, node: CertificationNode) -> Path:
        key = _digest(
            {
                "schema_version": _NODE_SCHEMA_VERSION,
                "release_sha": self.release_sha,
                "decision_epoch": self.epoch.isoformat(),
                "policy_version": self.policy_version,
                "node_id": node.node_id,
                "input_fingerprint": node.input_fingerprint,
            }
        )
        return (
            _root(self.values)
            / _SCHEMA_VERSION
            / self.release_sha
            / _epoch_key(self.epoch)
            / "nodes"
            / f"{key}.json"
        )

    def _load_success(self, node: CertificationNode) -> CertificationNodeResult | None:
        path = self._node_path(node)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        body = payload.get("body") if isinstance(payload, Mapping) else None
        if not isinstance(body, Mapping) or payload.get("sha256") != _digest(body):
            return None
        expected = {
            "schema_version": _NODE_SCHEMA_VERSION,
            "release_sha": self.release_sha,
            "decision_epoch": self.epoch.isoformat(),
            "policy_version": self.policy_version,
            "node_id": node.node_id,
            "input_fingerprint": node.input_fingerprint,
            "status": "qualified",
        }
        if any(body.get(key) != value for key, value in expected.items()):
            return None
        try:
            completed_at = _aware(
                datetime.fromisoformat(str(body["completed_at"]).replace("Z", "+00:00")),
                field_name="node_completed_at",
            )
        except (KeyError, TypeError, ValueError):
            return None
        return CertificationNodeResult(
            node_id=node.node_id,
            status="qualified",
            reused=True,
            evidence_complete_count=int(body.get("evidence_complete_count", 0)),
            completed_at=completed_at,
        )

    def _write_success(
        self,
        node: CertificationNode,
        *,
        evidence_complete_count: int,
    ) -> CertificationNodeResult:
        completed_at = datetime.now(timezone.utc)
        body: dict[str, object] = {
            "schema_version": _NODE_SCHEMA_VERSION,
            "release_sha": self.release_sha,
            "decision_epoch": self.epoch.isoformat(),
            "policy_version": self.policy_version,
            "node_id": node.node_id,
            "asset_class": node.asset_class,
            "provider_groups": list(node.provider_groups),
            "dependencies": list(node.dependencies),
            "input_fingerprint": node.input_fingerprint,
            "decision_eligible_count": int(node.decision_eligible_count),
            "evidence_complete_count": int(evidence_complete_count),
            "deadline": _aware(node.deadline, field_name="node_deadline").isoformat(),
            "completed_at": completed_at.isoformat(),
            "status": "qualified",
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
        _atomic_json(self._node_path(node), {"body": body, "sha256": _digest(body)})
        return CertificationNodeResult(
            node_id=node.node_id,
            status="qualified",
            reused=False,
            evidence_complete_count=int(evidence_complete_count),
            completed_at=completed_at,
        )

    @staticmethod
    def _retry_after(error: BaseException) -> datetime | None:
        seconds = getattr(error, "retry_after_seconds", None)
        if seconds is None:
            return None
        try:
            delay = float(seconds)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(delay) or delay <= 0.0:
            return None
        return datetime.now(timezone.utc) + timedelta(seconds=min(delay, 3600.0))

    def _write_failure(
        self,
        node: CertificationNode,
        *,
        error: BaseException,
    ) -> CertificationNodeResult:
        failed_at = datetime.now(timezone.utc)
        retry_after = self._retry_after(error)
        cause = _failure_cause(error)
        failure_message = _bounded_failure_text(error)
        failure_cause_type = None if cause is None else type(cause).__name__
        failure_cause_message = None if cause is None else _bounded_failure_text(cause)
        retryable = retry_after is not None
        body: dict[str, object] = {
            "schema_version": _NODE_SCHEMA_VERSION,
            "release_sha": self.release_sha,
            "decision_epoch": self.epoch.isoformat(),
            "policy_version": self.policy_version,
            "node_id": node.node_id,
            "asset_class": node.asset_class,
            "provider_groups": list(node.provider_groups),
            "dependencies": list(node.dependencies),
            "input_fingerprint": node.input_fingerprint,
            "decision_eligible_count": int(node.decision_eligible_count),
            "evidence_complete_count": 0,
            "deadline": _aware(node.deadline, field_name="node_deadline").isoformat(),
            "completed_at": failed_at.isoformat(),
            "status": "failed",
            "failure_type": type(error).__name__,
            "failure_message": failure_message,
            "failure_cause_type": failure_cause_type,
            "failure_cause_message": failure_cause_message,
            "retryable": retryable,
            "retry_after": None if retry_after is None else retry_after.isoformat(),
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
        _atomic_json(self._node_path(node), {"body": body, "sha256": _digest(body)})
        return CertificationNodeResult(
            node_id=node.node_id,
            status="failed",
            reused=False,
            evidence_complete_count=0,
            completed_at=failed_at,
            retry_after=retry_after,
            failure_type=type(error).__name__,
            failure_message=failure_message,
            failure_cause_type=failure_cause_type,
            failure_cause_message=failure_cause_message,
            retryable=retryable,
        )

    def _publish_manifest(
        self,
        *,
        nodes: Sequence[CertificationNode],
        results: Mapping[str, CertificationNodeResult],
    ) -> CertificationRunResult:
        required = tuple(sorted(node.node_id for node in nodes))
        completed = tuple(sorted(node_id for node_id, item in results.items() if item.status == "qualified"))
        reused = tuple(sorted(node_id for node_id, item in results.items() if item.status == "qualified" and item.reused))
        failed = tuple(sorted(node_id for node_id, item in results.items() if item.status != "qualified"))
        body: dict[str, object] = {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "release_sha": self.release_sha,
            "decision_epoch": self.epoch.isoformat(),
            "policy_version": self.policy_version,
            "required_nodes": list(required),
            "completed_nodes": list(completed),
            "reused_nodes": list(reused),
            "failed_nodes": list(failed),
            "node_results": {
                node_id: {
                    "status": item.status,
                    "reused": item.reused,
                    "evidence_complete_count": item.evidence_complete_count,
                    "failure_type": item.failure_type,
                    "failure_message": item.failure_message,
                    "failure_cause_type": item.failure_cause_type,
                    "failure_cause_message": item.failure_cause_message,
                    "retryable": item.retryable,
                    "retry_after": None if item.retry_after is None else item.retry_after.isoformat(),
                }
                for node_id, item in sorted(results.items())
            },
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
        manifest_id = _digest(body)
        payload = {"body": body, "sha256": manifest_id}
        directory = _root(self.values) / _SCHEMA_VERSION / self.release_sha / _epoch_key(self.epoch)
        immutable = directory / "manifests" / f"{manifest_id}.json"
        _immutable_json(immutable, payload)
        _atomic_json(directory / "latest.json", payload)
        return CertificationRunResult(
            manifest_id=manifest_id,
            required_nodes=required,
            completed_nodes=completed,
            reused_nodes=reused,
            failed_nodes=failed,
            path=immutable,
        )

    def run(
        self,
        nodes: Sequence[CertificationNode],
        runner: Callable[[CertificationNode], int],
    ) -> CertificationRunResult:
        ordered_nodes = tuple(nodes)
        by_id = {node.node_id: node for node in ordered_nodes}
        if len(by_id) != len(ordered_nodes):
            raise CertificationSchedulerError("certification DAG node identifiers must be unique")
        for node in ordered_nodes:
            missing = set(node.dependencies).difference(by_id)
            if missing:
                raise CertificationSchedulerError(
                    f"certification node {node.node_id} has unknown dependencies: "
                    + ", ".join(sorted(missing))
                )

        results: dict[str, CertificationNodeResult] = {}
        qualified: set[str] = set()
        pending: dict[str, CertificationNode] = {}
        for node in ordered_nodes:
            cached = self._load_success(node)
            if cached is not None:
                results[node.node_id] = cached
                qualified.add(node.node_id)
            else:
                pending[node.node_id] = node

        providers = tuple(group for node in ordered_nodes for group in node.provider_groups)
        budgets = ProviderBudgetRegistry(self.values, providers)
        workers = _worker_count(self.values, len(pending) or 1)
        running: dict[Future[int], tuple[CertificationNode, tuple[str, ...]]] = {}
        failures: set[str] = set()

        def submit_ready(executor: ThreadPoolExecutor) -> bool:
            submitted = False
            ready = [
                node
                for node in pending.values()
                if set(node.dependencies).issubset(qualified)
                and not set(node.dependencies).intersection(failures)
            ]
            ready.sort(
                key=lambda node: (
                    _aware(node.deadline, field_name="node_deadline"),
                    -int(node.priority),
                    node.node_id,
                )
            )
            running_ids = {node.node_id for node, _lease in running.values()}
            for node in ready:
                if len(running) >= workers:
                    break
                if node.node_id in running_ids:
                    continue
                lease = budgets.try_acquire(node.provider_groups)
                if lease is None:
                    continue
                future = executor.submit(runner, node)
                running[future] = (node, lease)
                pending.pop(node.node_id, None)
                submitted = True
            return submitted

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="certification-dag") as executor:
            while pending or running:
                submitted = submit_ready(executor)
                if not running:
                    if pending and not submitted:
                        blocked = tuple(sorted(pending))
                        for node_id in blocked:
                            node = pending.pop(node_id)
                            error = CertificationSchedulerError(
                                f"certification dependencies did not qualify for {node_id}"
                            )
                            results[node_id] = self._write_failure(node, error=error)
                            failures.add(node_id)
                        break
                    continue

                done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in done:
                    node, lease = running.pop(future)
                    budgets.release(lease)
                    try:
                        evidence_count = int(future.result())
                    except BaseException as error:  # noqa: BLE001 - persist exact worker failure.
                        results[node.node_id] = self._write_failure(node, error=error)
                        failures.add(node.node_id)
                    else:
                        results[node.node_id] = self._write_success(
                            node,
                            evidence_complete_count=evidence_count,
                        )
                        qualified.add(node.node_id)

        manifest = self._publish_manifest(nodes=ordered_nodes, results=results)
        if manifest.failed_nodes:
            details = []
            for node_id in manifest.failed_nodes:
                item = results[node_id]
                suffix = item.failure_type or "unqualified"
                if item.failure_message:
                    suffix += f": {item.failure_message}"
                if item.failure_cause_type:
                    suffix += f"; cause={item.failure_cause_type}"
                    if item.failure_cause_message:
                        suffix += f": {item.failure_cause_message}"
                suffix += f"; retryable={str(item.retryable).lower()}"
                if item.retry_after is not None:
                    suffix += f"; retry_after={item.retry_after.isoformat()}"
                details.append(f"{node_id}:{suffix}")
            raise CertificationSchedulerError(
                "required certification DAG nodes did not qualify: " + "; ".join(details)
            )
        return manifest


def _record_fingerprint(records: Sequence[object]) -> str:
    material = []
    for record in records:
        material.append(
            {
                "symbol": str(getattr(record, "symbol", "")).strip().upper(),
                "provider_symbol": str(getattr(record, "provider_symbol", "")).strip().upper(),
                "source_identifier": str(getattr(record, "source_identifier", "")).strip(),
                "instrument_identifier": getattr(record, "instrument_identifier", None),
                "asset_class": getattr(getattr(record, "asset_class", None), "value", None),
                "venue": str(getattr(record, "venue", "")).strip().upper(),
                "expiration_at": (
                    None
                    if getattr(record, "expiration_at", None) is None
                    else _aware(getattr(record, "expiration_at"), field_name="record_expiration_at").isoformat()
                ),
            }
        )
    return _digest(material)


def _provider_groups(asset_class: str) -> tuple[str, ...]:
    lane = str(asset_class).strip().lower()
    if lane in {"crypto", "cryptocurrency"}:
        return ("alpaca", "coinbase", "kraken")
    if lane in {"future", "futures"}:
        return ("cme", "massive")
    if lane in {"option", "options"}:
        return ("alpaca", "massive", "tradier")
    if lane in {"fx", "foreign_exchange"}:
        return ("eodhd", "massive", "twelve")
    if lane in {"equity", "stock", "stocks", "etf", "fund", "fixed_income", "bond"}:
        return ("eodhd", "massive", "twelve")
    return ("generic",)


def _market_node_valid_seconds(values: Mapping[str, str]) -> float:
    raw = str(values.get("CAPITAL_INTELLIGENCE_CERTIFICATION_MARKET_NODE_VALID_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_MARKET_NODE_VALID_SECONDS
    try:
        seconds = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_CERTIFICATION_MARKET_NODE_VALID_SECONDS must be numeric"
        ) from error
    if not math.isfinite(seconds) or seconds <= 0.0 or seconds > 86400.0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_CERTIFICATION_MARKET_NODE_VALID_SECONDS must be positive and no more than 86400"
        )
    return seconds


def _build_lane_nodes(
    core: Any,
    *,
    catalogs: Mapping[object, Sequence[object]],
    timestamp: datetime,
    resolved: object,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
    values: Mapping[str, str],
) -> tuple[tuple[CertificationNode, ...], Mapping[str, tuple[object, ...]]]:
    held = {str(item).strip().upper() for item in held_symbols if str(item).strip()}
    tracked = {str(item).strip().upper() for item in tracked_symbols if str(item).strip()}
    excluded = {str(item).strip().upper() for item in excluded_symbols if str(item).strip()}
    state_symbols = held | tracked
    deep_records_by_node: dict[str, tuple[object, ...]] = {}
    nodes: list[CertificationNode] = []
    valid_seconds = _market_node_valid_seconds(values)

    for asset_class in core._base._dynamic_discovery_lanes(catalogs):
        if not core._base._lane_is_scheduled(asset_class, timestamp):
            continue
        raw = catalogs.get(asset_class, ())
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise CertificationSchedulerError(
                f"{asset_class.value} catalog must be a sequence during certification DAG planning"
            )
        catalog_records = core._base._legacy._deduplicate(tuple(raw))
        records = []
        for item in catalog_records:
            if item.symbol in excluded:
                continue
            if (
                item.expiration_at is not None
                and item.expiration_at <= timestamp + timedelta(days=7)
            ):
                continue
            records.append(item)
        records = tuple(records)
        continuity = tuple(item for item in records if item.symbol in state_symbols)
        ordinary = tuple(item for item in records if item.symbol not in state_symbols)
        try:
            bounded = core.build_bounded_terminal_preselection(
                ordinary,
                as_of=timestamp,
                policy=resolved,
                progress_label=asset_class.value,
                chunk_size=core._PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE,
            )
        except core.BoundedTerminalScreeningError as error:
            raise CertificationSchedulerError(str(error)) from error
        deep_records = tuple(dict.fromkeys((*continuity, *bounded.nominated)))
        node_id = f"deep-market-evidence:{asset_class.value}"
        fingerprint = _digest(
            {
                "record_fingerprint": _record_fingerprint(deep_records),
                "policy_version": str(getattr(resolved, "version", "")),
                "asset_class": asset_class.value,
                "decision_epoch": timestamp.isoformat(),
            }
        )
        nodes.append(
            CertificationNode(
                node_id=node_id,
                asset_class=asset_class.value,
                provider_groups=_provider_groups(asset_class.value),
                input_fingerprint=fingerprint,
                deadline=timestamp + timedelta(seconds=valid_seconds),
                decision_eligible_count=len(deep_records),
                priority=len(continuity),
            )
        )
        deep_records_by_node[node_id] = deep_records
    return tuple(nodes), deep_records_by_node


def prewarm_comprehensive_discovery(
    core: Any,
    *,
    as_of: datetime,
    held_symbols: Sequence[str] = (),
    tracked_symbols: Sequence[str] = (),
    excluded_symbols: Sequence[str] = (),
    policy: object | None = None,
    values: Mapping[str, str] | None = None,
) -> CertificationRunResult | None:
    """Prequalify exact-epoch lane evidence while the canonical core stays authoritative."""

    resolved_values = os.environ if values is None else values
    if not _enabled(resolved_values):
        return None
    timestamp = core._base._legacy._aware(as_of, field_name="certification_dag_as_of")
    resolved = policy or core.ComprehensiveMarketDiscoveryPolicy()

    core.record_manual_cio_diagnostic_progress("certification_dag_catalog_dependency")
    catalogs = core._base._merge_certified_catalog(
        core._base.default_catalog_probe(timestamp, policy=resolved),
        as_of=timestamp,
    )
    if not isinstance(catalogs, Mapping):
        raise CertificationSchedulerError("certification DAG catalog dependency is not a mapping")
    core.record_manual_cio_diagnostic_progress(
        "certification_dag_catalog_dependency_complete",
        metrics={
            "catalog_records": sum(
                len(items) for items in catalogs.values() if isinstance(items, Sequence)
            )
        },
    )

    try:
        core.record_manual_cio_diagnostic_progress("certification_dag_provider_factor_dependency")
        core.ensure_provider_preselection_publication(
            catalogs,
            as_of=timestamp,
            policy=resolved,
            market_probe=core.default_provider_preselection_market_probe,
        )
        core.record_manual_cio_diagnostic_progress(
            "certification_dag_provider_factor_dependency_complete"
        )
    except core.ProviderPreselectionPublicationError as error:
        raise CertificationSchedulerError(str(error)) from error

    nodes, deep_records = _build_lane_nodes(
        core,
        catalogs=catalogs,
        timestamp=timestamp,
        resolved=resolved,
        held_symbols=held_symbols,
        tracked_symbols=tracked_symbols,
        excluded_symbols=excluded_symbols,
        values=resolved_values,
    )
    if not nodes:
        raise CertificationSchedulerError(
            "certification DAG found no scheduled comprehensive-discovery lanes"
        )

    scheduler = PersistentCertificationScheduler(
        values=resolved_values,
        release_sha=_release(resolved_values),
        epoch=timestamp,
        policy_version=str(getattr(resolved, "version", "")),
    )

    def run_node(node: CertificationNode) -> int:
        records = deep_records[node.node_id]
        core.record_manual_cio_diagnostic_progress(
            f"certification_dag:{node.asset_class}",
            metrics={
                "decision_eligible_records": len(records),
                "provider_budget_count": len(node.provider_groups),
            },
        )
        features = core.default_redundant_market_probe(records, timestamp, resolved)
        if not isinstance(features, Mapping):
            raise CertificationSchedulerError(
                f"{node.node_id} market evidence probe returned a non-mapping"
            )
        core.record_manual_cio_diagnostic_progress(
            f"certification_dag_complete:{node.asset_class}",
            metrics={
                "decision_eligible_records": len(records),
                "evidence_complete_records": len(features),
            },
        )
        return len(features)

    manifest = scheduler.run(nodes, run_node)
    core.record_manual_cio_diagnostic_progress(
        "certification_dag_ready",
        metrics={
            "required_nodes": len(manifest.required_nodes),
            "completed_nodes": len(manifest.completed_nodes),
            "reused_nodes": len(manifest.reused_nodes),
        },
    )
    return manifest


def install_certification_scheduler(core: Any) -> None:
    """Wrap canonical discovery with a provider-aware exact-epoch prewarming DAG."""

    if getattr(core, "_persistent_certification_scheduler_installed", False):
        return
    delegate = core.discover_comprehensive_markets

    def scheduled_discover_comprehensive_markets(
        *,
        as_of,
        held_symbols=(),
        tracked_symbols=(),
        excluded_symbols=(),
        catalog_probe=None,
        market_probe=None,
        preselection_probe=None,
        prior_cutoff_observations=(),
        policy=None,
    ):
        canonical = (
            catalog_probe is None
            and market_probe is None
            and preselection_probe is None
            and not tuple(prior_cutoff_observations)
        )
        if canonical and _enabled(os.environ):
            try:
                prewarm_comprehensive_discovery(
                    core,
                    as_of=as_of,
                    held_symbols=held_symbols,
                    tracked_symbols=tracked_symbols,
                    excluded_symbols=excluded_symbols,
                    policy=policy,
                    values=os.environ,
                )
            except CertificationSchedulerError as error:
                raise core._base._legacy.ComprehensiveMarketDiscoveryError(
                    f"persistent certification DAG is not ready: {error}"
                ) from error
        return delegate(
            as_of=as_of,
            held_symbols=held_symbols,
            tracked_symbols=tracked_symbols,
            excluded_symbols=excluded_symbols,
            catalog_probe=catalog_probe,
            market_probe=market_probe,
            preselection_probe=preselection_probe,
            prior_cutoff_observations=prior_cutoff_observations,
            policy=policy,
        )

    core.discover_comprehensive_markets = scheduled_discover_comprehensive_markets
    core._persistent_certification_scheduler_installed = True


__all__ = [
    "CertificationNode",
    "CertificationNodeResult",
    "CertificationRunResult",
    "CertificationSchedulerError",
    "PersistentCertificationScheduler",
    "ProviderBudgetRegistry",
    "install_certification_scheduler",
    "prewarm_comprehensive_discovery",
]
