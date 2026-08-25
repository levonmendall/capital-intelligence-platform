"""Run production telemetry without misclassifying governed observation states as failure.

The base collector intentionally returns exit 7 when its observation window ends without a
terminal CIO result. Release prequalification can legitimately remain active beyond that
window, and its public state is ``prequalifying`` rather than the older ``in_progress``.
This wrapper preserves every unsafe and terminal-failure exit while turning only verified
non-terminal observation states into successful observations. A release mismatch remains
strict by default; only the explicit schedule-only ``--allow-awaiting-deployment`` mode may
classify a credential-safe, paper-only mismatch as an awaiting-deployment observation.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

try:
    import capture_render_production_telemetry as _base
except ImportError:
    from scripts import capture_render_production_telemetry as _base


_ACTIVE_STATES = frozenset({"pending", "in_progress", "prequalifying"})
_ALLOW_AWAITING_DEPLOYMENT_FLAG = "--allow-awaiting-deployment"


def _argument_value(argv: Sequence[str], name: str) -> str | None:
    try:
        index = tuple(argv).index(name)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return str(argv[index + 1])


def _split_wrapper_arguments(argv: Sequence[str]) -> tuple[tuple[str, ...], bool]:
    allow_awaiting_deployment = False
    forwarded: list[str] = []
    for argument in argv:
        if argument == _ALLOW_AWAITING_DEPLOYMENT_FLAG:
            allow_awaiting_deployment = True
        else:
            forwarded.append(str(argument))
    return tuple(forwarded), allow_awaiting_deployment


def _active_exact_release(snapshot: Mapping[str, object]) -> bool:
    diagnostic = snapshot.get("diagnostic")
    return bool(
        snapshot.get("capture_state") == "ok"
        and isinstance(diagnostic, Mapping)
        and diagnostic.get("release_matches_expected") is True
        and str(diagnostic.get("state") or "").strip().lower() in _ACTIVE_STATES
    )


def _safe_release_mismatch(snapshot: Mapping[str, object]) -> bool:
    diagnostic = snapshot.get("diagnostic")
    return bool(
        snapshot.get("credential_safe") is True
        and snapshot.get("paper_only") is True
        and snapshot.get("real_money_authorized") is False
        and snapshot.get("capture_state") == "ok"
        and isinstance(diagnostic, Mapping)
        and diagnostic.get("release_matches_expected") is False
        and str(snapshot.get("expected_release") or "").strip()
    )


def _rewrite_timeline_last(snapshot: Mapping[str, object]) -> None:
    timeline_path_raw = _CURRENT_TIMELINE_PATH
    if timeline_path_raw is None:
        return
    timeline_path = Path(timeline_path_raw)
    if not timeline_path.exists():
        return
    try:
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return
    if isinstance(timeline, list) and timeline:
        timeline[-1] = dict(snapshot)
        _base._write_json(timeline_path, timeline)


def _rewrite_active_observation(path: Path, *, watched: bool) -> None:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, Mapping) or not _active_exact_release(snapshot):
        return
    rewritten = dict(snapshot)
    rewritten["failure_class"] = (
        "watch_window_elapsed" if watched else "active_prequalification"
    )
    rewritten["watch_window_elapsed"] = bool(watched)
    _base._write_json(path, rewritten)
    _rewrite_timeline_last(rewritten)


def _rewrite_awaiting_deployment(path: Path) -> bool:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(snapshot, Mapping) or not _safe_release_mismatch(snapshot):
        return False
    rewritten = dict(snapshot)
    rewritten["failure_class"] = "deployment_unresolved"
    rewritten["awaiting_deployment"] = True
    rewritten["deployment_resolution_required"] = True
    _base._write_json(path, rewritten)
    _rewrite_timeline_last(rewritten)
    print(json.dumps(rewritten, sort_keys=True), flush=True)
    return True


_CURRENT_TIMELINE_PATH: str | None = None


def main(argv: Sequence[str] | None = None) -> int:
    global _CURRENT_TIMELINE_PATH
    raw_arguments = tuple(sys.argv[1:] if argv is None else argv)
    arguments, allow_awaiting_deployment = _split_wrapper_arguments(raw_arguments)
    output_raw = _argument_value(arguments, "--output")
    watch_raw = _argument_value(arguments, "--watch-seconds") or "0"
    _CURRENT_TIMELINE_PATH = _argument_value(arguments, "--timeline-output")
    code = _base.main(arguments)

    if (
        code == _base._EXIT_RELEASE_MISMATCH
        and allow_awaiting_deployment
        and output_raw is not None
        and _rewrite_awaiting_deployment(Path(output_raw))
    ):
        return 0

    if code != _base._EXIT_TIMEOUT or output_raw is None:
        return code

    output = Path(output_raw)
    try:
        snapshot = json.loads(output.read_text(encoding="utf-8"))
        watched = float(watch_raw) > 0.0
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return code
    if not isinstance(snapshot, Mapping) or not _active_exact_release(snapshot):
        return code

    _rewrite_active_observation(output, watched=watched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
