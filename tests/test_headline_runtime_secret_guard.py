from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_guard(code: str, *, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    values = dict(os.environ)
    values.update(environment)
    values["CAPITAL_INTELLIGENCE_FORCE_HEADLINE_SECRET_GUARD"] = "true"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=values,
        check=True,
        capture_output=True,
        text=True,
    )


def test_provider_message_and_query_string_are_redacted() -> None:
    secret = "ALPHAVANTAGE-SECRET-12345"
    result = _run_guard(
        "import json; print(json.dumps({"
        "'error': 'We have detected your API key as " + secret + " and limited it',"
        "'url': 'https://example.test/query?apikey=" + secret + "&x=1'"
        "}, sort_keys=True))",
        environment={"ALPHA_VANTAGE_API_KEY": secret},
    )

    payload = json.loads(result.stdout)
    assert secret not in result.stdout
    assert payload["error"] == (
        "We have detected your API key as [REDACTED] and limited it"
    )
    assert payload["url"] == (
        "https://example.test/query?apikey=[REDACTED]&x=1"
    )


def test_canonical_eodhd_token_is_mapped_only_inside_guarded_process() -> None:
    secret = "EODHD-CANONICAL-SECRET-12345"
    result = _run_guard(
        "import os; print(os.environ.get('EODHD_API_KEY') == "
        "os.environ.get('CAPITAL_INTELLIGENCE_EODHD_API_TOKEN'))",
        environment={
            "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN": secret,
            "EODHD_API_KEY": "",
        },
    )

    assert result.stdout.strip() == "True"
    assert secret not in result.stdout


def test_nested_json_payloads_do_not_disclose_configured_credentials() -> None:
    secret = "FINNHUB-SECRET-12345"
    result = _run_guard(
        "import json; print(json.dumps({"
        "'sources': [{'error': 'Bearer " + secret + "'}],"
        "'detail': {'token': 'token=" + secret + "'}"
        "}))",
        environment={"FINNHUB_API_KEY": secret},
    )

    assert secret not in result.stdout
    assert result.stdout.count("[REDACTED]") == 2
