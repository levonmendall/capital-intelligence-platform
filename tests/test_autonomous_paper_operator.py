from __future__ import annotations

from dataclasses import dataclass

import run_autonomous_paper_operator


@dataclass
class _Cycle:
    cycle_key: str = "canonical-cio:test"
    status: str = "not_due"
    detail: str | None = None
    snapshot_identifier: str | None = None


class _Worker:
    def run_due(self, *, now):
        return _Cycle()

    def dispatch_pending(self):
        return ()


class _PublicCollection:
    state = "available"

    def to_dict(self):
        return {
            "state": "available",
            "detail": "collection complete",
            "exit_code": 0,
            "required_sources_ready": True,
            "source_count": 3,
            "failed_source_count": 0,
            "real_money_authorized": False,
        }


def _stub_public_collection(monkeypatch) -> None:
    monkeypatch.setattr(
        run_autonomous_paper_operator,
        "collect_public_live_information_if_due",
        lambda **_: _PublicCollection(),
    )


def _report(**kwargs):
    return {
        "report_state": "awaiting_cio_construction",
        "transaction_count": 0,
        "summary": "No complete canonical CIO construction is available yet.",
        "json_path": "database/cio_reports/pending_transactions_latest.json",
        "markdown_path": "database/cio_reports/pending_transactions_latest.md",
        "execution_state": kwargs.get("execution_state"),
    }


def test_operator_stays_operational_without_a_current_construction(
    monkeypatch,
    tmp_path,
) -> None:
    _stub_public_collection(monkeypatch)
    settings = run_autonomous_paper_operator.ApiSettings(
        journal_database=tmp_path / "journal.db",
        portfolio_database=tmp_path / "portfolio.db",
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT",
        "2020-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(
        run_autonomous_paper_operator,
        "publish_pending_transaction_report",
        _report,
    )
    monkeypatch.setattr(
        run_autonomous_paper_operator,
        "attempt_paper_execution",
        lambda **_: type(
            "Attempt",
            (),
            {
                "state": "idle",
                "to_dict": lambda self: {
                    "state": "idle",
                    "detail": "No construction",
                    "real_money_authorized": False,
                },
            },
        )(),
    )

    payload = run_autonomous_paper_operator._run_pass(
        settings=settings,
        worker=_Worker(),
    )

    assert payload["status"] == "operating"
    assert payload["public_live_information"]["state"] == "available"
    assert payload["paper_execution"]["state"] == "idle"
    assert payload["paper_trading_launch_open"] is True
    assert payload["pending_transaction_report"]["transaction_count"] == 0
    assert payload["fixture_stage_bindings_used"] is False
    assert payload["launch_clearance_required"] is False
    assert payload["real_money_authorized"] is False


def test_operator_publishes_report_but_holds_execution_before_launch(
    monkeypatch,
    tmp_path,
) -> None:
    _stub_public_collection(monkeypatch)
    settings = run_autonomous_paper_operator.ApiSettings(
        journal_database=tmp_path / "journal.db",
        portfolio_database=tmp_path / "portfolio.db",
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT",
        "2999-01-01T00:00:00+00:00",
    )
    published_states: list[str | None] = []

    def publish(**kwargs):
        published_states.append(kwargs.get("execution_state"))
        return _report(**kwargs)

    monkeypatch.setattr(
        run_autonomous_paper_operator,
        "publish_pending_transaction_report",
        publish,
    )

    def should_not_execute(**_):
        raise AssertionError("paper execution must not start before the launch time")

    monkeypatch.setattr(
        run_autonomous_paper_operator,
        "attempt_paper_execution",
        should_not_execute,
    )

    payload = run_autonomous_paper_operator._run_pass(
        settings=settings,
        worker=_Worker(),
    )

    assert payload["status"] == "operating"
    assert payload["paper_execution"]["state"] == "held"
    assert payload["paper_trading_launch_open"] is False
    assert published_states == ["scheduled", "held"]
    assert "scheduled to begin" in payload["paper_execution"]["detail"]


def test_docker_scheduler_uses_autonomous_operator_without_binding_secret() -> None:
    compose = open("docker-compose.yml", encoding="utf-8").read()
    assert '"run_autonomous_paper_operator.py", "--loop"' in compose
    assert "CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS_FILE:?" not in compose
