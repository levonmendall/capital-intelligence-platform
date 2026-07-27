"""Immutable, resumable historical backfills for external provider datasets.

Backfills land provider-native snapshots rather than silently normalizing them into
investment authority. Each date window is independently hashed and written once.
A rerun may reuse an identical artifact, but it cannot overwrite different bytes
at the same logical path.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from data.provider_dataset import (
    ProviderDatasetProvider,
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)


class ProviderBackfillError(RuntimeError):
    """Raised when a backfill plan or immutable artifact is invalid."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProviderBackfillError("backfill artifact must be finite JSON") from error


class ProviderBackfillState(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProviderBackfillTask:
    identifier: str
    provider_factory: str
    dataset_type: ProviderDatasetType
    provider_symbols: tuple[str, ...]
    start_at: datetime
    end_at: datetime
    window_days: int = 365
    limit: int = 1_000_000
    required: bool = True

    def __post_init__(self) -> None:
        for field_name in ("identifier", "provider_factory"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.dataset_type, ProviderDatasetType):
            raise TypeError("dataset_type must be ProviderDatasetType")
        if not isinstance(self.provider_symbols, tuple) or not self.provider_symbols:
            raise ValueError("provider_symbols must contain at least one symbol")
        normalized = tuple(
            _text(item, field_name="provider_symbol").upper()
            for item in self.provider_symbols
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("provider_symbols cannot contain duplicates")
        object.__setattr__(self, "provider_symbols", normalized)
        start = _aware(self.start_at, field_name="start_at")
        end = _aware(self.end_at, field_name="end_at")
        if end < start:
            raise ValueError("end_at cannot precede start_at")
        object.__setattr__(self, "start_at", start)
        object.__setattr__(self, "end_at", end)
        if isinstance(self.window_days, bool) or not isinstance(self.window_days, int):
            raise TypeError("window_days must be an integer")
        if not 1 <= self.window_days <= 3660:
            raise ValueError("window_days must be between 1 and 3660")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= self.limit <= 1_000_000:
            raise ValueError("limit must be between 1 and 1000000")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")


@dataclass(frozen=True, slots=True)
class ProviderBackfillPlan:
    identifier: str
    as_of: datetime
    tasks: tuple[ProviderBackfillTask, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _text(self.identifier, field_name="identifier"),
        )
        cutoff = _aware(self.as_of, field_name="as_of")
        object.__setattr__(self, "as_of", cutoff)
        if not isinstance(self.tasks, tuple) or not self.tasks:
            raise ValueError("tasks must contain at least one backfill task")
        if not all(isinstance(item, ProviderBackfillTask) for item in self.tasks):
            raise TypeError("tasks must contain ProviderBackfillTask values")
        identifiers = tuple(item.identifier for item in self.tasks)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("task identifiers cannot contain duplicates")
        future = tuple(item.identifier for item in self.tasks if item.end_at > cutoff)
        if future:
            raise ValueError(
                "task end_at cannot follow plan as_of: " + ", ".join(future)
            )


@dataclass(frozen=True, slots=True)
class ProviderBackfillArtifact:
    task_identifier: str
    provider: str
    provider_symbol: str
    dataset_type: ProviderDatasetType
    start_at: datetime
    end_at: datetime
    relative_path: str
    content_hash: str
    reused: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_identifier": self.task_identifier,
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "dataset_type": self.dataset_type.value,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "reused": self.reused,
        }


@dataclass(frozen=True, slots=True)
class ProviderBackfillReport:
    identifier: str
    plan_identifier: str
    evaluated_at: datetime
    state: ProviderBackfillState
    artifacts: tuple[ProviderBackfillArtifact, ...]
    failures: tuple[str, ...]
    required_failures: tuple[str, ...]

    @property
    def completed(self) -> bool:
        return self.state is ProviderBackfillState.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "provider-backfill-report.v1",
            "identifier": self.identifier,
            "plan_identifier": self.plan_identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "state": self.state.value,
            "artifact_count": len(self.artifacts),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "failures": list(self.failures),
            "required_failures": list(self.required_failures),
            "real_money_authorized": False,
        }


ProviderFactoryLoader = Callable[[str], ProviderDatasetProvider]


def load_provider_factory(reference: str) -> ProviderDatasetProvider:
    """Load ``module:function`` and require a raw dataset provider."""

    normalized = _text(reference, field_name="provider_factory")
    if ":" not in normalized:
        raise ProviderBackfillError("provider_factory must use module:function")
    module_name, function_name = normalized.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, function_name)
        provider = factory()
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        raise ProviderBackfillError(
            f"cannot load provider factory {normalized!r}"
        ) from error
    if not isinstance(provider, ProviderDatasetProvider):
        raise ProviderBackfillError(
            f"factory {normalized!r} does not return ProviderDatasetProvider"
        )
    return provider


class ProviderBackfillRunner:
    """Execute one immutable provider-native backfill plan."""

    def __init__(
        self,
        *,
        provider_loader: ProviderFactoryLoader = load_provider_factory,
    ) -> None:
        self._provider_loader = provider_loader

    def run(
        self,
        plan: ProviderBackfillPlan,
        *,
        output_directory: str | Path,
        evaluated_at: datetime,
    ) -> ProviderBackfillReport:
        if not isinstance(plan, ProviderBackfillPlan):
            raise TypeError("plan must be ProviderBackfillPlan")
        evaluated = _aware(evaluated_at, field_name="evaluated_at")
        root = Path(output_directory).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        providers: dict[str, ProviderDatasetProvider] = {}
        artifacts: list[ProviderBackfillArtifact] = []
        failures: list[str] = []
        required_failures: list[str] = []
        for task in plan.tasks:
            try:
                provider = providers.get(task.provider_factory)
                if provider is None:
                    provider = self._provider_loader(task.provider_factory)
                    providers[task.provider_factory] = provider
            except Exception as error:  # controlled report boundary
                message = f"{task.identifier}: provider load failed: {error}"
                failures.append(message)
                if task.required:
                    required_failures.append(message)
                continue
            for symbol in task.provider_symbols:
                for start_at, end_at in self._windows(task):
                    try:
                        snapshot = provider.fetch_dataset(
                            ProviderDatasetQuery(
                                dataset_type=task.dataset_type,
                                provider_symbol=symbol,
                                start_at=start_at,
                                end_at=end_at,
                                as_of=plan.as_of,
                                limit=task.limit,
                            )
                        )
                        artifacts.append(
                            self._persist(
                                root,
                                task=task,
                                symbol=symbol,
                                start_at=start_at,
                                end_at=end_at,
                                snapshot=snapshot,
                            )
                        )
                    except Exception as error:  # controlled report boundary
                        message = (
                            f"{task.identifier}:{symbol}:"
                            f"{start_at.date()}:{end_at.date()}: {error}"
                        )
                        failures.append(message)
                        if task.required:
                            required_failures.append(message)
        state = (
            ProviderBackfillState.FAILED
            if required_failures
            else ProviderBackfillState.PARTIAL
            if failures
            else ProviderBackfillState.COMPLETED
        )
        report = ProviderBackfillReport(
            identifier=f"{plan.identifier}:{evaluated.isoformat()}",
            plan_identifier=plan.identifier,
            evaluated_at=evaluated,
            state=state,
            artifacts=tuple(artifacts),
            failures=tuple(failures),
            required_failures=tuple(required_failures),
        )
        self._write_manifest(root, report)
        return report

    @staticmethod
    def _windows(
        task: ProviderBackfillTask,
    ) -> tuple[tuple[datetime, datetime], ...]:
        windows: list[tuple[datetime, datetime]] = []
        cursor = task.start_at
        step = timedelta(days=task.window_days)
        while cursor <= task.end_at:
            end_at = min(task.end_at, cursor + step - timedelta(microseconds=1))
            windows.append((cursor, end_at))
            cursor = end_at + timedelta(microseconds=1)
        return tuple(windows)

    @staticmethod
    def _persist(
        root: Path,
        *,
        task: ProviderBackfillTask,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
        snapshot: ProviderDatasetSnapshot,
    ) -> ProviderBackfillArtifact:
        safe_symbol = "".join(
            character if character.isalnum() or character in {"-", "_", "."} else "_"
            for character in symbol
        )
        relative = Path(task.identifier) / safe_symbol / (
            f"{start_at.date().isoformat()}__{end_at.date().isoformat()}.json"
        )
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = snapshot.to_dict()
        payload["backfill_task_identifier"] = task.identifier
        encoded = _canonical_bytes(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        reused = False
        if destination.exists():
            existing = destination.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise ProviderBackfillError(
                    f"immutable backfill artifact differs at {relative.as_posix()}"
                )
            reused = True
        else:
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(encoded)
            temporary.replace(destination)
        return ProviderBackfillArtifact(
            task_identifier=task.identifier,
            provider=snapshot.provider,
            provider_symbol=symbol,
            dataset_type=task.dataset_type,
            start_at=start_at,
            end_at=end_at,
            relative_path=relative.as_posix(),
            content_hash=digest,
            reused=reused,
        )

    @staticmethod
    def _write_manifest(root: Path, report: ProviderBackfillReport) -> None:
        destination = root / "backfill-report.json"
        encoded = _canonical_bytes(report.to_dict())
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(destination)


def load_provider_backfill_plan(path: str | Path) -> ProviderBackfillPlan:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProviderBackfillError(
            f"cannot load provider backfill plan {str(source)!r}"
        ) from error
    if not isinstance(payload, dict):
        raise ProviderBackfillError("provider backfill plan must be an object")
    if payload.get("schema_version") != "provider-backfill-plan.v1":
        raise ProviderBackfillError("unsupported provider backfill plan schema")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ProviderBackfillError("tasks must be a JSON array")
    try:
        tasks = tuple(
            ProviderBackfillTask(
                identifier=str(item["identifier"]),
                provider_factory=str(item["provider_factory"]),
                dataset_type=ProviderDatasetType(str(item["dataset_type"])),
                provider_symbols=tuple(item["provider_symbols"]),
                start_at=datetime.fromisoformat(str(item["start_at"]).replace("Z", "+00:00")),
                end_at=datetime.fromisoformat(str(item["end_at"]).replace("Z", "+00:00")),
                window_days=int(item.get("window_days", 365)),
                limit=int(item.get("limit", 1_000_000)),
                required=bool(item.get("required", True)),
            )
            for item in raw_tasks
            if isinstance(item, dict)
        )
        if len(tasks) != len(raw_tasks):
            raise ProviderBackfillError("every task must be a JSON object")
        return ProviderBackfillPlan(
            identifier=str(payload["identifier"]),
            as_of=datetime.fromisoformat(str(payload["as_of"]).replace("Z", "+00:00")),
            tasks=tasks,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ProviderBackfillError):
            raise
        raise ProviderBackfillError("provider backfill plan is invalid") from error


__all__ = [
    "ProviderBackfillArtifact",
    "ProviderBackfillError",
    "ProviderBackfillPlan",
    "ProviderBackfillReport",
    "ProviderBackfillRunner",
    "ProviderBackfillState",
    "ProviderBackfillTask",
    "load_provider_backfill_plan",
    "load_provider_factory",
]
