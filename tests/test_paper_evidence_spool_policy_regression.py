from __future__ import annotations

from operations.paper_evidence_spool import (
    _DEFAULT_MAX_MB,
    _DEFAULT_RESERVE_MB,
    _POLICY_VERSION,
)


def test_spool_policy_and_capacity_controls_are_unchanged():
    assert _POLICY_VERSION == "paper-evidence-symbol-spool.v2-transient-compressed"
    assert _DEFAULT_MAX_MB == 4096
    assert _DEFAULT_RESERVE_MB == 256
