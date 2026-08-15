from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from operations import qualified_equity_discovery as qualified


def test_production_consumer_uses_provider_free_point_in_time_snapshot(monkeypatch, tmp_path) -> None:
    as_of = datetime(2026, 8, 15, 3, 30, tzinfo=timezone.utc)
    observed: dict[str, object] = {}
    restored = SimpleNamespace(snapshot_id="equity-snapshot-test")
    result = SimpleNamespace(identifier="equity-discovery:test")

    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", "true")

    def ensure(**kwargs):
        observed["ensure"] = kwargs
        return SimpleNamespace(plane_as_of=as_of)

    def load(**kwargs):
        observed["load"] = kwargs
        return restored

    def view(snapshot, **kwargs):
        observed["view_snapshot"] = snapshot
        observed["view"] = kwargs
        return result

    def forbidden_provider_call(**kwargs):
        raise AssertionError("production consumer contacted provider-backed discovery")

    monkeypatch.setattr(qualified, "ensure_point_in_time_snapshot", ensure)
    monkeypatch.setattr(qualified, "load_equity_discovery_snapshot", load)
    monkeypatch.setattr(qualified, "view_equity_discovery_snapshot", view)
    monkeypatch.setattr(qualified._core, "discover_us_equities", forbidden_provider_call)

    actual = qualified.discover_us_equities(
        as_of=as_of,
        held_symbols=("AAPL",),
        tracked_symbols=("MSFT",),
        excluded_symbols=("SPY",),
    )

    assert actual is result
    assert observed["ensure"]["allow_refresh"] is False
    assert observed["ensure"]["cutoff"] == as_of
    assert observed["load"]["evidence_as_of"] == as_of
    assert observed["view_snapshot"] is restored
    assert observed["view"] == {
        "held_symbols": ("AAPL",),
        "tracked_symbols": ("MSFT",),
        "excluded_symbols": ("SPY",),
    }
    assert qualified.os.environ[
        "CAPITAL_INTELLIGENCE_CIO_US_EQUITY_DISCOVERY_SNAPSHOT_ID"
    ] == "equity-snapshot-test"
