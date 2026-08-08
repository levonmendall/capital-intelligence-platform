from __future__ import annotations

import run_render_service_certifying as startup


def test_render_startup_primes_release_before_service(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        startup,
        "prime_release_diagnostic_request",
        lambda: calls.append("prime") or 0,
    )
    monkeypatch.setattr(
        startup,
        "run_nonblocking_render_service",
        lambda: calls.append("service") or 0,
    )

    assert startup.main(()) == 0
    assert calls == ["prime", "service"]


def test_render_startup_fails_closed_when_primer_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        startup,
        "prime_release_diagnostic_request",
        lambda: calls.append("prime") or 2,
    )
    monkeypatch.setattr(
        startup,
        "run_nonblocking_render_service",
        lambda: calls.append("service") or 0,
    )

    assert startup.main(()) == 2
    assert calls == ["prime"]
