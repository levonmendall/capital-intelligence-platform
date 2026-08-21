"""Run production telemetry without misclassifying active prequalification as failure.

The base collector intentionally returns exit 7 when its observation window ends without a
terminal CIO result. Release prequalification can legitimately remain active beyond that
window, and its public state is ``prequalifying`` rather than the older ``in_progress``.
This wrapper preserves every unsafe, release-mismatch, and terminal-failure exit while
turning only a verified exact-release active prequalification into a successful observation.
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


def _argument_value(argv: Sequence[str], name: str) -> str | None:
    try:
        index = tuple(argv).index(name)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return str(argv[index + 1])


def _active_exact_release(snapshot: Mapping[str, object]) -> bool:
    diagnostic = snapshot.get("diagnostic")
    return bool(
        snapshot.get("capture_state") == "ok"
        and isinstance(diagnostic, Mapping)
        and diagnostic.get("release_matches_expected") is True
        and str(diagnostic.get("state") or "").strip().lower() in _ACTIVE_STATES
    )


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

    timeline_path_raw = _CURRENT_TIMELINE_PATH
    if timeline_path_raw is None:
        return
    timeline_path = Path(timeline_path_raw)
    if not timeline_path.exists():
        return
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    if isinstance(timeline, list) and timeline:
        timeline[-1] = rewritten
        _base._write_json(timeline_path, timeline)


_CURRENT_TIMELINE_PATH: str | None = None


def main(argv: Sequence[str] | None = None) -> int:
    global _CURRENT_TIMELINE_PATH
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    output_raw = _argument_value(arguments, "--output")
    watch_raw = _argument_value(arguments, "--watch-seconds") or "0"
    _CURRENT_TIMELINE_PATH = _argument_value(arguments, "--timeline-output")
    code = _base.main(arguments)
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
