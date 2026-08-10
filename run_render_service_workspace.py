"""Prepare Render's disposable runtime workspace before starting production.

Render's service plan enforces a hard 2 GB /tmp quota. Comprehensive evidence
collection and encrypted-backup verification can legitimately require larger
cycle-local working sets. This entrypoint creates the configured TMPDIR on the
persistent service disk and removes only abandoned, explicitly disposable
backup staging directories before importing the governed memory-safe bootstrap.
It has no investment, CIO, construction, execution, or real-money authority.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


_DISPOSABLE_BACKUP_PREFIXES = (
    "capital-intelligence-backup-",
    "capital-intelligence-verify-",
    "capital-intelligence-restore-",
)


def prepare_runtime_workspace(values: dict[str, str] | None = None) -> Path:
    environment = os.environ if values is None else values
    raw = environment.get("TMPDIR", "").strip()
    if not raw:
        raise RuntimeError("TMPDIR must be configured for the Render production service")
    workspace = Path(raw).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    for candidate in workspace.iterdir():
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        if not candidate.name.startswith(_DISPOSABLE_BACKUP_PREFIXES):
            continue
        shutil.rmtree(candidate)

    # tempfile.gettempdir() consults TMPDIR only if the directory exists. The
    # workspace must therefore be created before importing the production
    # bootstrap or any provider/backup module that may initialize tempfile.
    return workspace


def main() -> int:
    prepare_runtime_workspace()
    from run_render_service_memory_safe import main as run_service

    return run_service()


if __name__ == "__main__":
    raise SystemExit(main())
