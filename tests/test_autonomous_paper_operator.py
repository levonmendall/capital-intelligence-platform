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


def test_operator_stays_operational_without_a_current_construction(monkeypatch, tmp_path) -> None:
    settings = run_autonomous_paper_operator.ApiSettings(
        journal_database=tmp_path / "journal.db",
        portfolio_database=tmp_path / "portfolio.db",
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
    assert payload["paper_execution"]["state"] == "idle"
    assert payload["fixture_stage_bindings_used"] is False
    assert payload["launch_clearance_required"] is False
    assert payload["real_money_authorized"] is False


def test_docker_scheduler_uses_autonomous_operator_without_binding_secret() -> None:
    compose = open("docker-compose.yml", encoding="utf-8").read()
    assert '"run_autonomous_paper_operator.py", "--loop"' in compose
    assert "CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS_FILE:?" not in compose
