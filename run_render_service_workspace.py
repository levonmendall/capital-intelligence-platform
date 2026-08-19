"""Prepare Render's disposable runtime workspace before starting production.

Render's service plan enforces a hard 2 GB /tmp quota. Comprehensive evidence
collection and encrypted-backup verification can legitimately require larger
cycle-local working sets. This entrypoint creates the configured TMPDIR on the
persistent service disk, removes abandoned disposable runtime state, reclaims only
superseded release-bound reference-readiness cache, and establishes the governed
persistent-filesystem capacity before importing the memory-safe bootstrap.

Reusable reference components, the current exact-release manifest/progress, canonical
state, backups, and all investment/CIO artifacts are preserved. Historical market
history is a rebuildable performance cache and may be reset only when storage governance
requires it. This entrypoint has no investment, CIO, construction, execution, or
real-money authority.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from storage_governance import preflight_storage_capacity


_REFERENCE_RELEASE_PREFIXES = (
    "instrument-master-",
    "progress-",
)
_STORAGE_PREFLIGHT_ENV = "CAPITAL_INTELLIGENCE_STORAGE_PREFLIGHT_JSON"


def _release(values: dict[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or ""
    ).strip()


def _safe_release(release: str) -> str:
    return "".join(
        character
        for character in release
        if character.isalnum() or character in {"-", "_"}
    ) or "unknown"


def _reference_root(values: dict[str, str]) -> Path | None:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser() / "reference_readiness"


def _cleanup_disposable_workspace(workspace: Path) -> None:
    """Remove prior-process contents from the dedicated non-authority TMPDIR.

    The production TMPDIR is explicitly reserved for cycle-local scratch, paper-evidence
    spools, and backup staging. At service startup no prior process can retain authority
    over those files. Symlinks are never followed or removed.
    """

    for candidate in workspace.iterdir():
        if candidate.is_symlink():
            continue
        if candidate.is_dir():
            shutil.rmtree(candidate)
            continue
        if candidate.is_file():
            candidate.unlink(missing_ok=True)


def _cleanup_reference_readiness_cache(values: dict[str, str]) -> None:
    """Reclaim only non-authoritative readiness scratch and stale release bindings.

    Component checkpoints are deliberately retained because they are the reusable,
    freshness/integrity-qualified source used to avoid recollecting slow reference
    directories. Exact-release manifests and progress files from older commits cannot
    certify the current release and are safe to rebuild when that old release is no
    longer running.
    """

    root = _reference_root(values)
    if root is None or not root.is_dir():
        return

    # Atomic JSON writers can leave full-sized .tmp files after ENOSPC/interruption.
    # Scratch is never authoritative until os.replace/Path.replace succeeds.
    for candidate in root.rglob("*.json.tmp"):
        if candidate.is_file() and not candidate.is_symlink():
            candidate.unlink(missing_ok=True)

    current_release = _release(values)
    if not current_release:
        # Without an exact deployment identity, preserve all release-bound cache.
        return

    safe_release = _safe_release(current_release)
    keep = {
        f"instrument-master-{safe_release}.json",
        f"progress-{safe_release}.json",
    }
    for candidate in root.iterdir():
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if candidate.name in keep or not candidate.name.endswith(".json"):
            continue
        if candidate.name.startswith(_REFERENCE_RELEASE_PREFIXES):
            candidate.unlink(missing_ok=True)


def _publish_storage_preflight(
    environment: dict[str, str],
    snapshot: object,
) -> None:
    telemetry = getattr(snapshot, "telemetry", None)
    if not callable(telemetry):
        return
    payload = json.dumps(
        telemetry(),
        sort_keys=True,
        separators=(",", ":"),
    )
    environment[_STORAGE_PREFLIGHT_ENV] = payload
    print(f"[storage-governance] {payload}", flush=True)


def prepare_runtime_workspace(values: dict[str, str] | None = None) -> Path:
    environment = os.environ if values is None else values
    raw = environment.get("TMPDIR", "").strip()
    if not raw:
        raise RuntimeError("TMPDIR must be configured for the Render production service")
    workspace = Path(raw).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    _cleanup_disposable_workspace(workspace)
    _cleanup_reference_readiness_cache(environment)
    snapshot = preflight_storage_capacity(environment)
    if snapshot is not None:
        _publish_storage_preflight(environment, snapshot)

    # tempfile.gettempdir() consults TMPDIR only if the directory exists. The
    # workspace must therefore be created before importing the production
    # bootstrap or any provider/backup module that may initialize tempfile.
    return workspace


def main() -> int:
    prepare_runtime_workspace()
    import run_render_service_memory_safe as memory_safe
    from run_render_service_memory_safe import main as run_service
    from operations.progress_aware_release_certification import (
        install_resume_aware_release_dag_projection,
    )

    # The comprehensive research plane may legitimately resume a still-fresh discovery
    # epoch. Install its progress projection before the legacy parent watchdog.
    install_resume_aware_release_dag_projection()

    from operations.release_prequalification_parent_watchdog import (
        install_release_prequalification_parent_watchdog,
    )

    install_release_prequalification_parent_watchdog(memory_safe)

    # Install the capability operating-evidence startup gate first. Comprehensive
    # all-market preparation remains background/noncritical and cannot block the CIO.
    from operations.capability_scoped_render_bootstrap import (
        install as install_capability_scoped_render_bootstrap,
    )

    install_capability_scoped_render_bootstrap(memory_safe)

    # Revalidate capability evidence immediately before every diagnostic attempt. This
    # closes the retry-age gap where startup-qualified evidence could cross its freshness
    # boundary during a long first CIO attempt or bounded retry delay. The refresh itself
    # still runs through the independent resource-bounded evidence owner.
    from operations.capability_operating_retry_refresh import (
        install as install_capability_operating_retry_refresh,
    )

    install_capability_operating_retry_refresh(memory_safe)

    # Install the diagnostic seam last so both the capability startup wrapper and the
    # retry-freshness wrapper see capability-scoped environment semantics and share a
    # single durable CIO diagnostic owner rather than starting competing children.
    from operations.capability_scoped_release_diagnostic import (
        install as install_capability_scoped_release_diagnostic,
    )

    install_capability_scoped_release_diagnostic(memory_safe)
    return run_service()


if __name__ == "__main__":
    raise SystemExit(main())
