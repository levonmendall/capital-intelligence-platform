"""Validated subprocess bindings for all canonical daily-operation stages."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from operations.daily_leases import assert_current_stage_fence
from operations.daily_orchestration import CANONICAL_DAILY_STAGE_ORDER, CanonicalDailyStage


class StageBindingError(RuntimeError):
    """Raised when a deployment binding cannot execute or reconcile safely."""


class StageBindingTimeout(StageBindingError):
    """Raised when a stage command exceeds its configured wall-clock limit."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _field(payload: object, path: str) -> object:
    value = payload
    for part in path.split("."):
        if isinstance(value, Mapping):
            if part not in value:
                raise StageBindingError(
                    f"stage output is missing configured field {path!r}"
                )
            value = value[part]
            continue
        if isinstance(value, list) and part.isdigit():
            index = int(part)
            if index >= len(value):
                raise StageBindingError(
                    f"stage output list index is unavailable for {path!r}"
                )
            value = value[index]
            continue
        raise StageBindingError(
            f"stage output cannot resolve configured field {path!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class StageCommandBinding:
    stage: CanonicalDailyStage
    module: str
    argv: tuple[str, ...]
    output_fields: tuple[str, ...]
    retryable_exit_codes: tuple[int, ...] = ()
    timeout_seconds: float = 900.0

    def __post_init__(self) -> None:
        if not isinstance(self.stage, CanonicalDailyStage):
            raise TypeError("stage must be CanonicalDailyStage")
        object.__setattr__(
            self,
            "module",
            _text(self.module, field_name="module"),
        )
        for field_name in ("argv", "output_fields"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) for item in value
            ):
                raise TypeError(f"{field_name} must be a tuple of strings")
        if not self.output_fields:
            raise ValueError("output_fields cannot be empty")
        if not isinstance(self.retryable_exit_codes, tuple) or not all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in self.retryable_exit_codes
        ):
            raise TypeError("retryable_exit_codes must contain integers")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds,
            (int, float),
        ):
            raise TypeError("timeout_seconds must be numeric")
        if float(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        if importlib.util.find_spec(self.module) is None:
            raise ValueError(f"stage command module is unavailable: {self.module}")

    def resolve_arguments(self, replacements: Mapping[str, str]) -> tuple[str, ...]:
        resolved: list[str] = []
        for argument in self.argv:
            value = argument
            for token, replacement in replacements.items():
                value = value.replace("{" + token + "}", replacement)
            unresolved = tuple(
                part.split("}", 1)[0]
                for part in value.split("{")[1:]
                if "}" in part
            )
            if unresolved:
                raise StageBindingError(
                    f"stage {self.stage.value} has unresolved tokens: {unresolved}"
                )
            resolved.append(value)
        return tuple(resolved)


@dataclass(frozen=True, slots=True)
class StageBindingExecution:
    publication_identifier: str
    stage: CanonicalDailyStage
    delegate_output_identifiers: tuple[str, ...]
    delegate_module: str
    delegate_return_code: int
    fencing: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "publication_identifier": self.publication_identifier,
            "stage": self.stage.value,
            "delegate_output_identifiers": list(
                self.delegate_output_identifiers
            ),
            "delegate_module": self.delegate_module,
            "delegate_return_code": self.delegate_return_code,
            "fencing": dict(self.fencing),
            "schema_version": "canonical-stage-publication.v1",
        }


def load_stage_bindings(path: str | Path) -> dict[CanonicalDailyStage, StageCommandBinding]:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load daily stage bindings {source}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("daily stage bindings must encode an object")
    if payload.get("schema_version") != "canonical-daily-stage-bindings.v1":
        raise ValueError(
            "daily stage bindings must use canonical-daily-stage-bindings.v1"
        )
    raw_stages = payload.get("stages")
    if not isinstance(raw_stages, Mapping):
        raise ValueError("daily stage bindings require a stages object")
    expected = {stage.value for stage in CANONICAL_DAILY_STAGE_ORDER}
    actual = set(raw_stages)
    if actual != expected:
        raise ValueError(
            "daily stage bindings must configure all canonical stages: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    bindings: dict[CanonicalDailyStage, StageCommandBinding] = {}
    for stage in CANONICAL_DAILY_STAGE_ORDER:
        raw = raw_stages[stage.value]
        if not isinstance(raw, Mapping):
            raise ValueError(f"binding for {stage.value} must be an object")
        argv = raw.get("argv", ())
        output_fields = raw.get("output_fields", ())
        retryable = raw.get("retryable_exit_codes", ())
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError(f"binding argv for {stage.value} must be a string list")
        if not isinstance(output_fields, list) or not all(
            isinstance(item, str) for item in output_fields
        ):
            raise ValueError(
                f"binding output_fields for {stage.value} must be a string list"
            )
        if not isinstance(retryable, list) or not all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in retryable
        ):
            raise ValueError(
                f"binding retryable_exit_codes for {stage.value} must be integers"
            )
        bindings[stage] = StageCommandBinding(
            stage=stage,
            module=str(raw.get("module") or ""),
            argv=tuple(argv),
            output_fields=tuple(output_fields),
            retryable_exit_codes=tuple(retryable),
            timeout_seconds=float(raw.get("timeout_seconds", 900.0)),
        )
    return bindings


def validate_stage_bindings(path: str | Path) -> dict[str, object]:
    bindings = load_stage_bindings(path)
    return {
        "status": "valid",
        "binding_path": str(Path(path).expanduser()),
        "stages": [stage.value for stage in CANONICAL_DAILY_STAGE_ORDER],
        "timeouts_seconds": {
            stage.value: bindings[stage].timeout_seconds
            for stage in CANONICAL_DAILY_STAGE_ORDER
        },
        "schema_version": "canonical-daily-stage-bindings.v1",
    }


def execute_stage_binding(
    binding: StageCommandBinding,
    *,
    replacements: Mapping[str, str],
) -> StageBindingExecution:
    if not isinstance(binding, StageCommandBinding):
        raise TypeError("binding must be StageCommandBinding")
    context = assert_current_stage_fence()
    if context.stage is not binding.stage:
        raise StageBindingError(
            "active stage fence does not match configured stage binding"
        )
    arguments = binding.resolve_arguments(replacements)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", binding.module, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=binding.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise StageBindingTimeout(
            f"stage {binding.stage.value} exceeded "
            f"{binding.timeout_seconds:g} seconds"
        ) from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "no output").strip()
        classification = (
            "retryable"
            if completed.returncode in binding.retryable_exit_codes
            else "terminal"
        )
        raise StageBindingError(
            f"stage {binding.stage.value} delegate exited {completed.returncode} "
            f"({classification}): {detail}"
        )
    raw = completed.stdout.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StageBindingError(
            f"stage {binding.stage.value} delegate did not emit one JSON document"
        ) from error
    if not isinstance(payload, Mapping):
        raise StageBindingError("stage delegate output must be a JSON object")
    identifiers = tuple(
        _text(_field(payload, path), field_name=path)
        for path in binding.output_fields
    )
    assert_current_stage_fence()
    digest = hashlib.sha256(
        "|".join(
            (
                context.operation_identifier,
                context.stage.value,
                str(context.operation_fencing_token),
                str(context.stage_fencing_token),
                binding.module,
                *identifiers,
            )
        ).encode("utf-8")
    ).hexdigest()[:24]
    publication_identifier = (
        f"stage-publication:{context.operation_identifier}:"
        f"{context.stage.value}:{context.stage_fencing_token}:{digest}"
    )
    return StageBindingExecution(
        publication_identifier=publication_identifier,
        stage=binding.stage,
        delegate_output_identifiers=identifiers,
        delegate_module=binding.module,
        delegate_return_code=completed.returncode,
        fencing=context.to_dict(),
    )


__all__ = [
    "StageBindingError",
    "StageBindingExecution",
    "StageBindingTimeout",
    "StageCommandBinding",
    "execute_stage_binding",
    "load_stage_bindings",
    "validate_stage_bindings",
]
