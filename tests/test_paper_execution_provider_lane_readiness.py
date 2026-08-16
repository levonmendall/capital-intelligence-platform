from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import paper_execution_runtime as runtime
from paper_execution_runtime import PaperExecutionMode


AS_OF = datetime(2026, 8, 15, 20, 0, tzinfo=timezone.utc)


def _construction(symbol: str) -> dict[str, object]:
    return {
        "request_identifier": f"construction:test:{symbol.lower()}",
        "as_of": AS_OF.isoformat(),
        "status": "feasible",
        "trades": [
            {
                "symbol": symbol,
                "side": "buy",
                "from_weight": 0.0,
                "to_weight": 0.1,
                "trade_weight": 0.1,
            }
        ],
    }


def _briefing() -> dict[str, object]:
    return {
        "decision_identifier": "decision:test-provider-lane",
        "as_of": AS_OF.isoformat(),
    }


def _clear_alpaca_credentials(monkeypatch) -> None:
    for name in (
        "APCA_API_KEY_ID",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_KEY",
        "APCA_API_SECRET_KEY",
        "ALPACA_API_SECRET_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def _configure_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE", "automatic")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_CONSTRUCTION_MAX_AGE_HOURS", "24")
    _clear_alpaca_credentials(monkeypatch)
    monkeypatch.setattr(runtime, "validate_pilot_construction", lambda *_args, **_kwargs: None)
    construction_path = tmp_path / "construction.json"
    profiles_path = tmp_path / "profiles.json"
    construction_path.write_text("{}", encoding="utf-8")
    profiles_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        runtime,
        "_materialize_execution_inputs",
        lambda *_args, **_kwargs: (construction_path, profiles_path),
    )


def test_direct_only_construction_does_not_require_alpaca_credentials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    direct = SimpleNamespace(symbol="EURUSD", uses_direct_market_provider=True)
    monkeypatch.setattr(
        runtime,
        "load_execution_paper_universe",
        lambda _construction: SimpleNamespace(instruments=(direct,)),
    )

    def runner(_arguments):
        print(
            json.dumps(
                {
                    "status": "completed",
                    "execution_identifier": "execution:direct-only",
                    "real_money_authorized": False,
                }
            )
        )
        return 0

    assert runtime.paper_execution_mode() is PaperExecutionMode.AUTOMATIC
    attempt = runtime.attempt_paper_execution(
        construction=_construction("EURUSD"),
        briefing=_briefing(),
        now=AS_OF,
        runner=runner,
    )

    assert attempt.completed is True
    assert attempt.execution_identifier == "execution:direct-only"
    assert attempt.mode is PaperExecutionMode.AUTOMATIC


def test_alpaca_backed_construction_still_requires_alpaca_credentials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    alpaca = SimpleNamespace(symbol="VTI", uses_direct_market_provider=False)
    monkeypatch.setattr(
        runtime,
        "load_execution_paper_universe",
        lambda _construction: SimpleNamespace(instruments=(alpaca,)),
    )
    called = False

    def runner(_arguments):
        nonlocal called
        called = True
        return 0

    attempt = runtime.attempt_paper_execution(
        construction=_construction("VTI"),
        briefing=_briefing(),
        now=AS_OF,
        runner=runner,
    )

    assert attempt.state == "disabled"
    assert "Alpaca paper credentials" in attempt.detail
    assert called is False


def test_explicit_disabled_mode_remains_authoritative(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE", "disabled")

    assert runtime.paper_execution_mode() is PaperExecutionMode.DISABLED
    attempt = runtime.attempt_paper_execution(
        construction=_construction("EURUSD"),
        briefing=_briefing(),
        now=AS_OF,
    )

    assert attempt.state == "disabled"
    assert attempt.mode is PaperExecutionMode.DISABLED
