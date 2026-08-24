from __future__ import annotations

from pathlib import Path

from operations import evidence_file_cache_release as cache_release


def test_reference_cache_scope_has_no_investment_authority(tmp_path: Path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }
    observed = cache_release.completed_operating_evidence_paths(values)
    assert all("portfolio" not in path.name for path in observed)
    assert all("execution" not in path.name for path in observed)
