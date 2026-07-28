from __future__ import annotations

import json

from run_alpaca_paper_broker_smoke import MINIMUM_SMOKE_NOTIONAL, build_parser, main


def test_smoke_cli_defaults_to_current_alpaca_minimum() -> None:
    args = build_parser().parse_args(())

    assert MINIMUM_SMOKE_NOTIONAL == 10.0
    assert args.notional == MINIMUM_SMOKE_NOTIONAL


def test_smoke_cli_rejects_subminimum_before_network_access(capsys) -> None:
    result = main(("--notional", "9.99"))
    payload = json.loads(capsys.readouterr().out)

    assert result == 4
    assert "at least $10.00" in payload["error"]
    assert payload["real_money_authorized"] is False
