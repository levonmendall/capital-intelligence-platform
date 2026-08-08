from __future__ import annotations

import run_render_service_nonblocking as bootstrap


def test_release_diagnostic_is_primed_before_diagnostic_thread_starts(
    monkeypatch,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-current",
    }
    events: list[str] = []

    class FakeThread:
        def __init__(self, *, name, target, kwargs, daemon):
            assert name == "manual-cio-release-diagnostic"
            assert target is bootstrap._run_release_diagnostic_after_readiness
            assert kwargs["values"] is values
            assert daemon is True
            self._alive = False

        def start(self) -> None:
            events.append("thread-start")
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

    def prime(received_values):
        assert received_values is values
        events.append("prime")
        return 0

    monkeypatch.setattr(bootstrap, "prime_release_diagnostic_request", prime)
    monkeypatch.setattr(bootstrap.threading, "Thread", FakeThread)

    thread = bootstrap._start_release_diagnostic(values)

    assert thread is not None
    assert events == ["prime", "thread-start"]


def test_disabled_release_diagnostic_does_not_prime(monkeypatch) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "false",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-current",
    }

    def unexpected_prime(_values):
        raise AssertionError("disabled release diagnostics must not create coordination state")

    monkeypatch.setattr(
        bootstrap,
        "prime_release_diagnostic_request",
        unexpected_prime,
    )

    assert bootstrap._start_release_diagnostic(values) is None