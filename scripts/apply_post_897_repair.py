from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_prewarm() -> None:
    path = Path("operations/comprehensive_discovery_structural_prewarm.py")
    text = path.read_text(encoding="utf-8")

    start = text.index("def _provider_lane_partition(\n")
    end = text.index("\n\ndef _provider_initial_lane_items(\n", start)
    partition = '''def _provider_lane_partition(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    acquisition,
    decision_epoch: datetime,
) -> tuple[
    tuple[tuple[int, CandidateAssetClass], ...],
    tuple[tuple[int, CandidateAssetClass], ...],
]:
    """Partition scheduled lanes by canonical exact-publication validity.

    The existing reuse-only provider-publication validator is used only as a scheduling
    hint. A present but invalid exact-request artifact is treated like a missing publication
    and prioritized for bounded repair. Reuse-only probing cannot invoke provider I/O and
    grants no evidence authority; the later serialized transaction remains authoritative.
    """

    lane_items = tuple(acquisition._scheduled_lane_items(decision_epoch))
    validation_values = dict(values)
    validation_values[acquisition._REUSE_ONLY_ENV] = "true"
    missing: list[tuple[int, CandidateAssetClass]] = []
    present: list[tuple[int, CandidateAssetClass]] = []
    for index, asset_class in lane_items:
        try:
            report = acquisition.prepare_lane_provider_publication(
                request_path,
                values=validation_values,
                asset_class_value=asset_class.value,
                index=index,
            )
            ready_hint = bool(report.get("publication_ready"))
        except (OSError, RuntimeError, TypeError, ValueError):
            ready_hint = False
        if ready_hint:
            present.append((index, asset_class))
        else:
            missing.append((index, asset_class))
    return tuple(missing), tuple(present)
'''
    text = text[:start] + partition + text[end:]

    old_initial = '''def _provider_initial_lane_items(
    request_path: str | Path,
    *,
    acquisition,
    decision_epoch: datetime,
) -> tuple[tuple[int, CandidateAssetClass], ...]:
    """Run absent publication paths first without dropping any scheduled lane."""

    missing, present = _provider_lane_partition(
        request_path,
        acquisition=acquisition,
        decision_epoch=decision_epoch,
    )
    return missing + present
'''
    new_initial = '''def _provider_initial_lane_items(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    acquisition,
    decision_epoch: datetime,
) -> tuple[tuple[int, CandidateAssetClass], ...]:
    """Run unresolved exact publications first without dropping any scheduled lane."""

    missing, present = _provider_lane_partition(
        request_path,
        values=values,
        acquisition=acquisition,
        decision_epoch=decision_epoch,
    )
    return missing + present
'''
    text = replace_once(text, old_initial, new_initial, label="initial lane helper")

    replay_start = text.index("def _provider_replay_lane_items(\n")
    replay_end = text.index("\n\ndef _provider_replay_reserve_seconds(", replay_start)
    replay = '''def _provider_replay_lane_items(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    acquisition,
    decision_epoch: datetime,
) -> tuple[tuple[int, CandidateAssetClass], ...]:
    """Target missing or canonically invalid exact publications on bounded replay.

    The reuse-only canonical validator supplies only a scheduling hint. It cannot perform
    provider I/O or certify evidence. Invalid artifacts are targeted before already-valid
    lanes, while replay remains inside the original absolute provider window and unchanged
    single-replay limit.
    """

    missing, present = _provider_lane_partition(
        request_path,
        values=values,
        acquisition=acquisition,
        decision_epoch=decision_epoch,
    )
    return missing or (missing + present)
'''
    text = text[:replay_start] + replay + text[replay_end:]

    text = replace_once(
        text,
        '''    initial_missing, initial_present = _provider_lane_partition(
        request_path,
        acquisition=acquisition,
        decision_epoch=decision_epoch,
    )''',
        '''    initial_missing, initial_present = _provider_lane_partition(
        request_path,
        values=resolved,
        acquisition=acquisition,
        decision_epoch=decision_epoch,
    )''',
        label="initial partition call",
    )
    text = replace_once(
        text,
        '''            missing_after_initial, _present_after_initial = _provider_lane_partition(
                request_path,
                acquisition=acquisition,
                decision_epoch=decision_epoch,
            )''',
        '''            missing_after_initial, _present_after_initial = _provider_lane_partition(
                request_path,
                values=resolved,
                acquisition=acquisition,
                decision_epoch=decision_epoch,
            )''',
        label="post-initial partition call",
    )
    text = replace_once(
        text,
        '''            scheduled_override = _provider_replay_lane_items(
                request_path,
                acquisition=acquisition,
                decision_epoch=decision_epoch,
            )''',
        '''            scheduled_override = _provider_replay_lane_items(
                request_path,
                values=resolved,
                acquisition=acquisition,
                decision_epoch=decision_epoch,
            )''',
        label="replay selection call",
    )
    text = replace_once(
        text,
        '''    final_missing, _final_present = _provider_lane_partition(
        request_path,
        acquisition=acquisition,
        decision_epoch=decision_epoch,
    )''',
        '''    final_missing, _final_present = _provider_lane_partition(
        request_path,
        values=resolved,
        acquisition=acquisition,
        decision_epoch=decision_epoch,
    )''',
        label="final partition call",
    )
    path.write_text(text, encoding="utf-8")


def patch_provider_child() -> None:
    path = Path("operations/epoch_scoped_provider_acquisition.py")
    text = path.read_text(encoding="utf-8")
    old = '''        else:
            prepare_lane_provider_publication(
                args.request,
                values=dict(os.environ),
                asset_class_value=str(args.asset_class),
                index=int(args.index),
            )'''
    new = '''        else:
            resolved = dict(os.environ)
            from operations.evidence_preparation_progress import (
                install_post_public_provider_progress,
            )

            # This interpreter owns the actual provider requests. The existing progress hook
            # records only distinct completed request work units, so cross-process liveness is
            # visible without synthetic heartbeats or any change to the parent stall budget.
            install_post_public_provider_progress(resolved)
            prepare_lane_provider_publication(
                args.request,
                values=resolved,
                asset_class_value=str(args.asset_class),
                index=int(args.index),
            )'''
    path.write_text(
        replace_once(text, old, new, label="provider child progress installation"),
        encoding="utf-8",
    )


def write_tests() -> None:
    Path("tests/test_post_897_provider_repairs.py").write_text(
        '''from __future__ import annotations

from datetime import datetime, timezone

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_prewarm as prewarm
from operations import epoch_scoped_provider_acquisition as acquisition
from operations import evidence_preparation_progress as preparation


def _epoch() -> datetime:
    return datetime(2026, 9, 1, 15, 22, 16, tzinfo=timezone.utc)


def test_existing_but_invalid_exact_publication_is_unresolved(monkeypatch, tmp_path) -> None:
    lane = (4, CandidateAssetClass.INTERNATIONAL_EQUITY)
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: (lane,))
    canonical = tmp_path / "provider-preselection-004-international_equity.json"
    canonical.write_text("present-but-invalid", encoding="utf-8")
    observed_values: list[dict[str, str]] = []

    def reject_invalid(request_path, *, values, asset_class_value, index):
        assert request_path == tmp_path / "request.json"
        assert asset_class_value == CandidateAssetClass.INTERNATIONAL_EQUITY.value
        assert index == 4
        observed_values.append(dict(values))
        raise RuntimeError("exact-epoch provider publication is unavailable or invalid")

    monkeypatch.setattr(acquisition, "prepare_lane_provider_publication", reject_invalid)

    unresolved, ready = prewarm._provider_lane_partition(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        acquisition=acquisition,
        decision_epoch=_epoch(),
    )

    assert canonical.exists()
    assert unresolved == (lane,)
    assert ready == ()
    assert observed_values[0][acquisition._REUSE_ONLY_ENV] == "true"


def test_valid_exact_publication_remains_reuse_priority(monkeypatch, tmp_path) -> None:
    lane = (4, CandidateAssetClass.INTERNATIONAL_EQUITY)
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: (lane,))
    monkeypatch.setattr(
        acquisition,
        "prepare_lane_provider_publication",
        lambda *args, **kwargs: {"publication_ready": True, "reused": True},
    )

    unresolved, ready = prewarm._provider_lane_partition(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        acquisition=acquisition,
        decision_epoch=_epoch(),
    )

    assert unresolved == ()
    assert ready == (lane,)


def test_provider_child_installs_real_request_progress_before_provider_work(monkeypatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(
        preparation,
        "install_post_public_provider_progress",
        lambda values=None: order.append("progress-installed"),
    )
    monkeypatch.setattr(
        acquisition,
        "prepare_lane_provider_publication",
        lambda *args, **kwargs: order.append("provider-publication") or {},
    )

    result = acquisition.main(
        [
            "--request",
            "/tmp/request.json",
            "--asset-class",
            CandidateAssetClass.US_EQUITY.value,
            "--index",
            "0",
        ]
    )

    assert result == 0
    assert order == ["progress-installed", "provider-publication"]


def test_governed_post_897_limits_remain_unchanged() -> None:
    assert prewarm._PROVIDER_REPLAY_LIMIT == 1
    assert acquisition._MAX_FANOUT_SECONDS == 300.0
    assert acquisition._DOWNSTREAM_RESERVE_SECONDS == 480.0
    assert acquisition._DEFAULT_WORKERS == 6
    assert acquisition._MAX_WORKERS == 6
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    patch_prewarm()
    patch_provider_child()
    write_tests()
