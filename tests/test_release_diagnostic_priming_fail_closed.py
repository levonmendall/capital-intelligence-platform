from __future__ import annotations

import pytest

import run_render_service_nonblocking as bootstrap


def test_priming_failure_prevents_diagnostic_thread_start(monkeypatch) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-current",
    }

    def fail_prime(_values):
        raise ValueError("invalid durable diagnostic state")

    def unexpected_thread(*args, **kwargs):
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(bootstrap, "prime_release_diagnostic_request", fail_prime)
    monkeypatch.setattr(bootstrap.threading, "Thread", unexpected_thread)

    with pytest.raises(ValueError, match="invalid durable diagnostic state"):
        bootstrap._start_release_diagnostic(values)