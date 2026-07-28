"""Run exact approved paper implementations inside the Streamlit runtime.

The worker deliberately remains paper-only. It consumes the same SQLite authorities
written by the authenticated application, materializes the exact approved construction
and matching free-pilot profiles, then delegates to the canonical consent-gated paper
executor. Alpaca supplies account, session, asset, and IEX quote evidence; fills remain
internal simulations and no broker order endpoint is called.
"""

from __future__ import annotations

import io
import json
import os
import time
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import streamlit as st

from governance.paper_decision_approval import (
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


@dataclass(frozen=True, slots=True)
class StreamlitPaperExecutionAttempt:
    state: str
    detail: str
    attempted_at: datetime | None = None
    exit_code: int | None = None
    execution_identifier: str | None = None

    @property
    def completed(self) -> bool:
        return self.state == "completed"


Runner = Callable[[Sequence[str] | None], int]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _environment() -> str:
    return (
        os.getenv("CAPITAL_INTELLIGENCE_ENVIRONMENT")
        or os.getenv("CAPITAL_INTELLIGENCE_DEPLOYMENT_ENVIRONMENT")
        or "development"
    ).strip().lower()


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


def streamlit_paper_execution_enabled() -> bool:
    explicit = os.getenv("CAPITAL_INTELLIGENCE_STREAMLIT_PAPER_EXECUTION_ENABLED")
    if explicit is not None:
        return _truthy(explicit)
    return _environment() in {"development", "paper", "test"} and _credentials_available()


def _development_bypass_enabled() -> bool:
    explicit = os.getenv(
        "CAPITAL_INTELLIGENCE_STREAMLIT_PAPER_EXECUTION_DEVELOPMENT_BYPASS"
    )
    if explicit is not None:
        return _truthy(explicit)
    return _environment() in {"development", "paper", "test"}


def _data_dir() -> Path:
    return Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()


def _approval_database() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE")
    return Path(configured).expanduser() if configured else _data_dir() / "paper_test_governance.db"


def _artifact_directory() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_ARTIFACT_DIR")
    path = Path(configured).expanduser() if configured else _data_dir() / "paper_execution_artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _retry_seconds() -> int:
    raw = os.getenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_RETRY_SECONDS", "60")
    try:
        value = int(raw)
    except ValueError:
        return 60
    return max(5, min(value, 3600))


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
    lock_directory = _artifact_directory() / "locks"
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
    base = _artifact_directory() / f"{safe_identifier}-{construction_hash[:16]}"
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
    arguments = [
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
    if _development_bypass_enabled():
        arguments.append("--development-bypass-launch-gate")
    return arguments


def attempt_approved_paper_execution(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    now: datetime | None = None,
    runner: Runner = run_approved_paper_execution,
) -> StreamlitPaperExecutionAttempt:
    if not streamlit_paper_execution_enabled():
        return StreamlitPaperExecutionAttempt(
            state="disabled",
            detail=(
                "Automatic paper execution is disabled or Alpaca paper credentials are "
                "not available in this runtime."
            ),
        )
    if not isinstance(construction, Mapping) or not isinstance(briefing, Mapping):
        return StreamlitPaperExecutionAttempt(
            state="idle",
            detail="No complete CIO decision and construction are available.",
        )
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    decision_identifier = str(briefing.get("decision_identifier", "")).strip()
    construction_identifier = str(construction.get("request_identifier", "")).strip()
    if not decision_identifier or not construction_identifier:
        return StreamlitPaperExecutionAttempt(
            state="blocked",
            detail="Decision or construction identity is incomplete.",
            attempted_at=timestamp,
        )

    construction_hash = canonical_construction_sha256(construction)
    approval_store = SQLitePaperDecisionApprovalStore(_approval_database())
    approval_store.verify_integrity()
    approval = approval_store.latest(decision_identifier, construction_identifier)
    if approval is None or approval.state is not PaperDecisionApprovalState.APPROVED:
        return StreamlitPaperExecutionAttempt(
            state="idle",
            detail="No active exact paper approval is available.",
        )
    if approval.construction_sha256 != construction_hash or not approval.active_at(timestamp):
        return StreamlitPaperExecutionAttempt(
            state="blocked",
            detail="The exact paper approval is expired or no longer matches construction.",
            attempted_at=timestamp,
        )

    status_path = _artifact_directory() / f"{construction_hash}.status.json"
    prior = _load_status(status_path)
    if prior is not None and prior.get("state") not in {"completed"}:
        try:
            previous_time = datetime.fromisoformat(str(prior["attempted_at"]))
        except (KeyError, TypeError, ValueError):
            previous_time = None
        if previous_time is not None and timestamp - previous_time < timedelta(seconds=_retry_seconds()):
            return StreamlitPaperExecutionAttempt(
                state=str(prior.get("state", "held")),
                detail=str(prior.get("detail", "Paper execution is waiting for retry.")),
                attempted_at=previous_time,
                exit_code=(None if prior.get("exit_code") is None else int(prior["exit_code"])),
                execution_identifier=(
                    None
                    if prior.get("execution_identifier") is None
                    else str(prior["execution_identifier"])
                ),
            )

    with _construction_lease(construction_hash) as acquired:
        if not acquired:
            return StreamlitPaperExecutionAttempt(
                state="held",
                detail="Another paper-execution attempt is already running.",
                attempted_at=timestamp,
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
            detail = "The approved paper implementation completed successfully."
        elif exit_code == 3:
            state = "held"
            detail = str(
                payload.get("error")
                or payload.get("status")
                or "Execution is held until market, quote, or liquidity controls clear."
            )
        else:
            state = "blocked"
            detail = str(payload.get("error") or payload.get("status") or "Paper execution was blocked.")
        _atomic_json(
            status_path,
            {
                "state": state,
                "detail": detail,
                "attempted_at": timestamp.isoformat(),
                "exit_code": exit_code,
                "execution_identifier": execution_identifier,
                "real_money_authorized": False,
            },
        )
        return StreamlitPaperExecutionAttempt(
            state=state,
            detail=detail,
            attempted_at=timestamp,
            exit_code=exit_code,
            execution_identifier=execution_identifier,
        )


@st.fragment(run_every="30s")
def render_background_paper_execution_worker(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
) -> None:
    attempt = attempt_approved_paper_execution(
        construction=construction,
        briefing=briefing,
    )
    if attempt.completed:
        st.rerun()


__all__ = [
    "StreamlitPaperExecutionAttempt",
    "attempt_approved_paper_execution",
    "render_background_paper_execution_worker",
    "streamlit_paper_execution_enabled",
]
