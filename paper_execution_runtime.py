"""Autonomous or manual execution of exact canonical paper constructions.

This module is intentionally paper-only. It never creates a recommendation, changes
construction, relaxes eligibility, routes to a live brokerage endpoint, or grants
real-money authority. Automatic mode replaces a redundant per-construction click with
an append-only exact-hash system authorization and then delegates to the existing
consent-gated canonical executor.
"""

from __future__ import annotations

import io
import json
import os
import time
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from governance.paper_decision_approval import (
    PaperDecisionApprovalEvent,
    PaperDecisionApprovalState,
    SQLitePaperDecisionApprovalStore,
    canonical_construction_sha256,
)
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
    validate_pilot_construction,
)
from run_approved_paper_execution import main as run_approved_paper_execution


class PaperExecutionMode(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class PaperExecutionAttempt:
    state: str
    detail: str
    attempted_at: datetime | None = None
    exit_code: int | None = None
    execution_identifier: str | None = None
    authorization_identifier: str | None = None
    mode: PaperExecutionMode = PaperExecutionMode.AUTOMATIC

    @property
    def completed(self) -> bool:
        return self.state == "completed"

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "detail": self.detail,
            "attempted_at": (
                None if self.attempted_at is None else self.attempted_at.isoformat()
            ),
            "exit_code": self.exit_code,
            "execution_identifier": self.execution_identifier,
            "authorization_identifier": self.authorization_identifier,
            "mode": self.mode.value,
            "paper_only": True,
            "real_money_authorized": False,
        }


Runner = Callable[[Sequence[str] | None], int]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _credentials_available() -> bool:
    key_names = ("APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY")
    secret_names = (
        "APCA_API_SECRET_KEY",
        "ALPACA_API_SECRET_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_SECRET",
    )
    return any(os.getenv(name, "").strip() for name in key_names) and any(
        os.getenv(name, "").strip() for name in secret_names
    )


def paper_execution_mode() -> PaperExecutionMode:
    """Resolve the paper execution mode.

    Credentials imply automatic paper operation unless the operator explicitly chooses
    manual or disabled mode. The old Streamlit enable flag remains a compatibility
    switch; an explicit false value disables execution.
    """

    configured = os.getenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE")
    if configured is not None and configured.strip():
        try:
            return PaperExecutionMode(configured.strip().lower())
        except ValueError as error:
            allowed = ", ".join(item.value for item in PaperExecutionMode)
            raise ValueError(
                f"CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE must be one of {allowed}"
            ) from error
    legacy = os.getenv("CAPITAL_INTELLIGENCE_STREAMLIT_PAPER_EXECUTION_ENABLED")
    if legacy is not None and not _truthy(legacy):
        return PaperExecutionMode.DISABLED
    return (
        PaperExecutionMode.AUTOMATIC
        if _credentials_available()
        else PaperExecutionMode.DISABLED
    )


def paper_execution_enabled() -> bool:
    return paper_execution_mode() is not PaperExecutionMode.DISABLED


def _data_dir() -> Path:
    return Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()


def approval_database() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE")
    return (
        Path(configured).expanduser()
        if configured
        else _data_dir() / "paper_test_governance.db"
    )


def artifact_directory() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_ARTIFACT_DIR")
    path = (
        Path(configured).expanduser()
        if configured
        else _data_dir() / "paper_execution_artifacts"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _retry_seconds() -> int:
    raw = os.getenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_RETRY_SECONDS", "60")
    try:
        value = int(raw)
    except ValueError:
        return 60
    return max(5, min(value, 3600))


def _authorization_ttl() -> timedelta:
    raw = os.getenv("CAPITAL_INTELLIGENCE_AUTONOMOUS_PAPER_AUTHORIZATION_HOURS", "24")
    try:
        hours = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_AUTONOMOUS_PAPER_AUTHORIZATION_HOURS must be numeric"
        ) from error
    if not 0.1 <= hours <= 168:
        raise ValueError("autonomous paper authorization must be between 0.1 and 168 hours")
    return timedelta(hours=hours)


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_status(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_runner_payload(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


@contextmanager
def _construction_lease(construction_hash: str):
    lock_directory = artifact_directory() / "locks"
    lock_directory.mkdir(parents=True, exist_ok=True)
    lock_path = lock_directory / f"{construction_hash}.lock"
    stale_after = max(120, _retry_seconds() * 2)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0
            if age <= stale_after:
                yield False
                return
            try:
                lock_path.unlink()
            except OSError:
                yield False
                return
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield True
    finally:
        if descriptor is not None:
            os.close(descriptor)
            try:
                lock_path.unlink()
            except OSError:
                pass


def _trade_symbols(construction: Mapping[str, Any]) -> tuple[str, ...]:
    trades = construction.get("trades")
    if not isinstance(trades, list):
        raise ValueError("construction trades must be a list")
    symbols: list[str] = []
    for item in trades:
        if not isinstance(item, Mapping):
            raise ValueError("construction trade entries must be objects")
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError("construction trade symbol is unavailable")
        if symbol not in symbols:
            symbols.append(symbol)
    return tuple(symbols)


def _materialize_execution_inputs(
    construction: Mapping[str, Any],
    *,
    construction_hash: str,
) -> tuple[Path, Path]:
    universe_path = Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_FREE_PAPER_PILOT_UNIVERSE",
            str(DEFAULT_UNIVERSE_PATH),
        )
    ).expanduser()
    universe = load_free_paper_pilot_universe(universe_path)
    validate_pilot_construction(construction, universe=universe)
    symbols = _trade_symbols(construction)
    profile_map = {item["symbol"]: item for item in universe.profiles_payload()}
    missing = sorted(set(symbols) - set(profile_map))
    if missing:
        raise ValueError(f"paper execution profiles are unavailable for {missing}")
    profiles = [profile_map[symbol] for symbol in symbols]

    construction_identifier = str(construction["request_identifier"]).strip()
    if not construction_identifier:
        raise ValueError("construction request_identifier is unavailable")
    safe_identifier = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in construction_identifier
    )[-96:]
    base = artifact_directory() / f"{safe_identifier}-{construction_hash[:16]}"
    construction_path = base.with_suffix(".construction.json")
    profiles_path = base.with_suffix(".profiles.json")
    _atomic_json(construction_path, dict(construction))
    _atomic_json(profiles_path, profiles)
    return construction_path, profiles_path


def _runner_arguments(
    *,
    construction_path: Path,
    profiles_path: Path,
    decision_identifier: str,
    as_of: datetime,
) -> list[str]:
    return [
        "--construction",
        str(construction_path),
        "--decision-identifier",
        decision_identifier,
        "--profiles",
        str(profiles_path),
        "--session-provider",
        "providers.alpaca_paper:create_alpaca_paper_session_provider",
        "--quote-provider",
        "providers.alpaca_paper:create_alpaca_paper_quote_provider",
        "--as-of",
        as_of.isoformat(),
        "--portfolio-code",
        "COMPOUNDING",
    ]


def _automatic_authorization(
    *,
    store: SQLitePaperDecisionApprovalStore,
    decision_identifier: str,
    construction_identifier: str,
    construction_hash: str,
    timestamp: datetime,
) -> PaperDecisionApprovalEvent | None:
    """Create or reuse exact autonomous authorization without overriding a human stop."""

    latest = store.latest(decision_identifier, construction_identifier)
    if latest is not None:
        if latest.construction_sha256 != construction_hash:
            # A different payload under the same immutable construction ID is an
            # integrity problem, not a reason to silently create another authority.
            raise ValueError(
                "construction identifier resolves to a different canonical payload"
            )
        if latest.state is PaperDecisionApprovalState.EXECUTED:
            return latest
        if latest.state in {
            PaperDecisionApprovalState.DECLINED,
            PaperDecisionApprovalState.REVOKED,
        }:
            return None
        if latest.active_at(timestamp):
            return latest

    return store.approve(
        decision_identifier=decision_identifier,
        construction_identifier=construction_identifier,
        construction_sha256=construction_hash,
        actor_user_id="system:autonomous-paper-policy",
        actor_session_id="worker:autonomous-paper-operator",
        occurred_at=timestamp,
        rationale=(
            "Automatic paper mode authorized this exact canonical construction. "
            "All data, eligibility, portfolio, liquidity, cost, and reconciliation "
            "controls remain independently enforced."
        ),
        ttl=_authorization_ttl(),
    )


def attempt_paper_execution(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    now: datetime | None = None,
    runner: Runner = run_approved_paper_execution,
    mode: PaperExecutionMode | None = None,
) -> PaperExecutionAttempt:
    resolved_mode = mode or paper_execution_mode()
    if resolved_mode is PaperExecutionMode.DISABLED:
        return PaperExecutionAttempt(
            state="disabled",
            detail="Paper execution is disabled or paper credentials are unavailable.",
            mode=resolved_mode,
        )
    if not _credentials_available():
        return PaperExecutionAttempt(
            state="disabled",
            detail="Alpaca paper credentials are unavailable in this runtime.",
            mode=resolved_mode,
        )
    if not isinstance(construction, Mapping) or not isinstance(briefing, Mapping):
        return PaperExecutionAttempt(
            state="idle",
            detail="No complete CIO decision and construction are available.",
            mode=resolved_mode,
        )
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    decision_identifier = str(briefing.get("decision_identifier", "")).strip()
    construction_identifier = str(construction.get("request_identifier", "")).strip()
    briefing_as_of = str(briefing.get("as_of", "")).strip()
    construction_as_of = str(construction.get("as_of", "")).strip()
    if briefing_as_of and construction_as_of and briefing_as_of != construction_as_of:
        return PaperExecutionAttempt(
            state="idle",
            detail="The latest CIO briefing and construction are from different cycles.",
            attempted_at=timestamp,
            mode=resolved_mode,
        )
    if construction_as_of:
        try:
            constructed_at = datetime.fromisoformat(construction_as_of.replace("Z", "+00:00"))
        except ValueError:
            return PaperExecutionAttempt(
                state="blocked",
                detail="Construction timestamp is invalid.",
                attempted_at=timestamp,
                mode=resolved_mode,
            )
        if constructed_at.tzinfo is None or constructed_at.utcoffset() is None:
            return PaperExecutionAttempt(
                state="blocked",
                detail="Construction timestamp must be timezone-aware.",
                attempted_at=timestamp,
                mode=resolved_mode,
            )
        raw_age = os.getenv("CAPITAL_INTELLIGENCE_PAPER_CONSTRUCTION_MAX_AGE_HOURS", "24")
        try:
            maximum_age = timedelta(hours=float(raw_age))
        except ValueError as error:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_PAPER_CONSTRUCTION_MAX_AGE_HOURS must be numeric"
            ) from error
        if maximum_age <= timedelta(0):
            raise ValueError("paper construction maximum age must be positive")
        if timestamp < constructed_at or timestamp - constructed_at > maximum_age:
            return PaperExecutionAttempt(
                state="idle",
                detail="The canonical paper construction is not current enough to execute.",
                attempted_at=timestamp,
                mode=resolved_mode,
            )
    if not decision_identifier or not construction_identifier:
        return PaperExecutionAttempt(
            state="blocked",
            detail="Decision or construction identity is incomplete.",
            attempted_at=timestamp,
            mode=resolved_mode,
        )

    # Validate the exact implementation before creating any authorization event.
    universe_path = Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_FREE_PAPER_PILOT_UNIVERSE",
            str(DEFAULT_UNIVERSE_PATH),
        )
    ).expanduser()
    try:
        validate_pilot_construction(
            construction,
            universe=load_free_paper_pilot_universe(universe_path),
        )
    except (OSError, TypeError, ValueError) as error:
        return PaperExecutionAttempt(
            state="blocked",
            detail=str(error),
            attempted_at=timestamp,
            mode=resolved_mode,
        )

    construction_hash = canonical_construction_sha256(construction)
    store = SQLitePaperDecisionApprovalStore(approval_database())
    store.verify_integrity()
    authorization = store.latest(decision_identifier, construction_identifier)
    if resolved_mode is PaperExecutionMode.AUTOMATIC:
        authorization = _automatic_authorization(
            store=store,
            decision_identifier=decision_identifier,
            construction_identifier=construction_identifier,
            construction_hash=construction_hash,
            timestamp=timestamp,
        )
        if authorization is None:
            return PaperExecutionAttempt(
                state="paused",
                detail=(
                    "Autonomous execution is paused for this exact construction by "
                    "the latest human decline or revocation."
                ),
                attempted_at=timestamp,
                mode=resolved_mode,
            )
        if authorization.state is PaperDecisionApprovalState.EXECUTED:
            return PaperExecutionAttempt(
                state="completed",
                detail="This exact paper construction was already executed.",
                attempted_at=timestamp,
                execution_identifier=authorization.execution_identifier,
                authorization_identifier=authorization.identifier,
                mode=resolved_mode,
            )
    elif authorization is None or authorization.state is not PaperDecisionApprovalState.APPROVED:
        return PaperExecutionAttempt(
            state="idle",
            detail="Manual mode is waiting for exact paper approval.",
            mode=resolved_mode,
        )

    assert authorization is not None
    if authorization.construction_sha256 != construction_hash or not authorization.active_at(timestamp):
        return PaperExecutionAttempt(
            state="blocked",
            detail="The exact paper authorization is expired or no longer matches construction.",
            attempted_at=timestamp,
            authorization_identifier=authorization.identifier,
            mode=resolved_mode,
        )

    status_path = artifact_directory() / f"{construction_hash}.status.json"
    prior = _load_status(status_path)
    if prior is not None:
        if prior.get("state") == "completed":
            return PaperExecutionAttempt(
                state="completed",
                detail=str(prior.get("detail") or "Paper execution completed."),
                attempted_at=(
                    None
                    if prior.get("attempted_at") is None
                    else datetime.fromisoformat(str(prior["attempted_at"]))
                ),
                exit_code=(None if prior.get("exit_code") is None else int(prior["exit_code"])),
                execution_identifier=(
                    None
                    if prior.get("execution_identifier") is None
                    else str(prior["execution_identifier"])
                ),
                authorization_identifier=authorization.identifier,
                mode=resolved_mode,
            )
        try:
            previous_time = datetime.fromisoformat(str(prior["attempted_at"]))
        except (KeyError, TypeError, ValueError):
            previous_time = None
        if previous_time is not None and timestamp - previous_time < timedelta(
            seconds=_retry_seconds()
        ):
            return PaperExecutionAttempt(
                state=str(prior.get("state", "held")),
                detail=str(prior.get("detail", "Paper execution is waiting for retry.")),
                attempted_at=previous_time,
                exit_code=(None if prior.get("exit_code") is None else int(prior["exit_code"])),
                execution_identifier=(
                    None
                    if prior.get("execution_identifier") is None
                    else str(prior["execution_identifier"])
                ),
                authorization_identifier=authorization.identifier,
                mode=resolved_mode,
            )

    with _construction_lease(construction_hash) as acquired:
        if not acquired:
            return PaperExecutionAttempt(
                state="held",
                detail="Another paper-execution attempt is already running.",
                attempted_at=timestamp,
                authorization_identifier=authorization.identifier,
                mode=resolved_mode,
            )
        try:
            construction_path, profiles_path = _materialize_execution_inputs(
                construction,
                construction_hash=construction_hash,
            )
            arguments = _runner_arguments(
                construction_path=construction_path,
                profiles_path=profiles_path,
                decision_identifier=decision_identifier,
                as_of=timestamp,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = int(runner(arguments))
            payload = _parse_runner_payload(output.getvalue())
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            exit_code = 4
            payload = {"status": "blocked", "error": str(error)}

        execution_identifier = (
            None
            if payload.get("execution_identifier") is None
            else str(payload["execution_identifier"])
        )
        if exit_code == 0:
            state = "completed"
            detail = "The canonical paper implementation completed successfully."
        elif exit_code == 3:
            state = "held"
            detail = str(
                payload.get("error")
                or payload.get("status")
                or "Execution is held until market, quote, or liquidity controls clear."
            )
        else:
            state = "blocked"
            detail = str(
                payload.get("error")
                or payload.get("status")
                or "Paper execution was blocked."
            )
        _atomic_json(
            status_path,
            {
                "state": state,
                "detail": detail,
                "attempted_at": timestamp.isoformat(),
                "exit_code": exit_code,
                "execution_identifier": execution_identifier,
                "authorization_identifier": authorization.identifier,
                "mode": resolved_mode.value,
                "real_money_authorized": False,
            },
        )
        return PaperExecutionAttempt(
            state=state,
            detail=detail,
            attempted_at=timestamp,
            exit_code=exit_code,
            execution_identifier=execution_identifier,
            authorization_identifier=authorization.identifier,
            mode=resolved_mode,
        )


# Backward-compatible name used by existing imports and tests.
attempt_approved_paper_execution = attempt_paper_execution


__all__ = [
    "PaperExecutionAttempt",
    "PaperExecutionMode",
    "approval_database",
    "artifact_directory",
    "attempt_approved_paper_execution",
    "attempt_paper_execution",
    "paper_execution_enabled",
    "paper_execution_mode",
]
