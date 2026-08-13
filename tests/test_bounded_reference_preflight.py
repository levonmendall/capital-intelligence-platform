from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import run_bounded_manual_cio_diagnostic as bounded


def test_reference_readiness_runs_before_bounded_cio_child(monkeypatch, tmp_path) -> None:
    events = []
    child_environments = []

    def prepare(values):
        events.append("reference")
        values["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"] = str(
            tmp_path / "manifest.json"
        )
        values["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"] = "manifest-test"
        return SimpleNamespace(
            manifest_id="manifest-test",
            captured_at=datetime(2026, 8, 13, 20, 30, tzinfo=timezone.utc),
            catalog_counts=(("future", 1), ("international_equity", 1)),
            eodhd_exchanges=("LSE",),
            futures_roots=("ES",),
        )

    class Process:
        pid = 1234
        returncode = 0

        def poll(self):
            return 0

    def popen(*_args, **kwargs):
        events.append("popen")
        child_environments.append(dict(kwargs["env"]))
        return Process()

    monkeypatch.setattr(bounded, "prepare_reference_readiness", prepare)
    monkeypatch.setattr(bounded.subprocess, "Popen", popen)
    monkeypatch.setattr(
        bounded,
        "_wait_with_resource_bounds",
        lambda *_args, **_kwargs: (0, False, False, 0, 0),
    )
    monkeypatch.setattr(
        bounded,
        "_container_memory_kib",
        lambda _values: (100, 1000, "test"),
    )

    result = bounded.run_bounded_diagnostic(
        values={
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        },
        timeout_seconds=10,
    )

    assert result == 0
    assert events == ["reference", "popen"]
    assert child_environments[0]["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"] == (
        "manifest-test"
    )


def test_reference_failure_prevents_bounded_cio_child(monkeypatch, tmp_path) -> None:
    called = []

    def fail(_values):
        raise bounded.ReferenceReadinessError("reference provider unavailable")

    monkeypatch.setattr(bounded, "prepare_reference_readiness", fail)
    monkeypatch.setattr(
        bounded,
        "fail_reference_readiness_request",
        lambda _values, *, detail: called.append(detail),
    )
    monkeypatch.setattr(
        bounded.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bounded CIO child must not start")
        ),
    )

    result = bounded.run_bounded_diagnostic(
        values={
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        },
        timeout_seconds=10,
    )

    assert result == 3
    assert called and "reference provider unavailable" in called[0]
