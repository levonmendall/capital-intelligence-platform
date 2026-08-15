from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from operations import qualified_paper_evidence as qualified


def test_production_probe_loads_exact_snapshot_without_refresh(monkeypatch, tmp_path) -> None:
    as_of = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)
    observed: dict[str, object] = {}
    universe = SimpleNamespace(identifier="universe:test")
    payload = {"bars": {}, "quotes": {}, "macro": {}}

    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", "true")

    def ensure(**kwargs):
        observed["ensure"] = kwargs
        return SimpleNamespace(plane_as_of=as_of)

    def load(**kwargs):
        observed["load"] = kwargs
        return SimpleNamespace(snapshot_id="paper-snapshot-test", payload=payload)

    monkeypatch.setattr(qualified, "ensure_point_in_time_snapshot", ensure)
    monkeypatch.setattr(qualified, "load_paper_evidence_snapshot", load)

    actual = qualified.qualified_paper_evidence_probe(universe, as_of)

    assert actual is payload
    assert observed["ensure"]["allow_refresh"] is False
    assert observed["ensure"]["cutoff"] == as_of
    assert observed["load"]["evidence_as_of"] == as_of
    assert observed["load"]["universe"] is universe
    assert qualified.os.environ[
        "CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"
    ] == "paper-snapshot-test"
