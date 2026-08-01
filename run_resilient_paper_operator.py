"""Run the canonical autonomous paper operator with resilient scan-state handling."""

from __future__ import annotations

from typing import Sequence

import run_autonomous_paper_operator as operator
from production_context_state_resilience import (
    invalidate_reuse_preserving_success,
    recording_context_preparer,
)


def configure_resilient_state_lifecycle() -> None:
    """Install explicit state adapters without changing investment authority."""

    operator._invalidate_context_reuse_cache = invalidate_reuse_preserving_success
    operator.prepare_production_context_for_cycle = recording_context_preparer(
        operator.prepare_production_context_for_cycle
    )


def main(argv: Sequence[str] | None = None) -> int:
    configure_resilient_state_lifecycle()
    return operator.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
