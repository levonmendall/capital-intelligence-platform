from __future__ import annotations

import threading

import pytest

import run_render_service_memory_safe as runtime


def test_release_diagnostic_is_primed_only_after_evidence_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-123",
    }
    order: list[str] = []

    monkeypatch.setattr(
        runtime,
        "_prequalify_release_evidence",
        lambda _values: order.append("prequalify") or True,
    )
    monkeypatch.setattr(
        runtime.render_bootstrap,
        "prime_release_diagnostic_request",
        lambda _values: order.append("prime"),
    )
    monkeypatch.setattr(
        runtime.render_bootstrap,
        "_run_release_diagnostic_after_readiness",
        lambda _values, *, not_before: order.append("diagnostic"),
    )

    thread = runtime._start_release_diagnostic_after_prequalification(values)

    assert isinstance(thread, threading.Thread)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert order == ["prequalify", "prime", "diagnostic"]


def test_failed_prequalification_never_creates_cio_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-123",
    }
    primed = False
    diagnostic_started = False

    monkeypatch.setattr(runtime, "_prequalify_release_evidence", lambda _values: False)

    def unexpected_prime(_values):
        nonlocal primed
        primed = True

    def unexpected_diagnostic(_values, *, not_before):
        del not_before
        nonlocal diagnostic_started
        diagnostic_started = True

    monkeypatch.setattr(
        runtime.render_bootstrap,
        "prime_release_diagnostic_request",
        unexpected_prime,
    )
    monkeypatch.setattr(
        runtime.render_bootstrap,
        "_run_release_diagnostic_after_readiness",
        unexpected_diagnostic,
    )

    thread = runtime._start_release_diagnostic_after_prequalification(values)

    assert isinstance(thread, threading.Thread)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert primed is False
    assert diagnostic_started is False
