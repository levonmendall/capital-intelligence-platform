from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations.all_markets_paper_rehearsal import (
    run_all_markets_paper_rehearsal,
)
from operations.universal_paper_availability import (
    ALL_CLASSIFIED_ASSET_CLASSES,
    assess_universal_paper_availability,
    load_universal_paper_asset_class_scope,
)
from run_universal_paper_availability import main

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "config" / "universal_paper_asset_classes.json"
AS_OF = datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)


def test_scope_exactly_declares_every_classified_asset_class() -> None:
    scope = load_universal_paper_asset_class_scope(SCOPE)

    assert {item.asset_class for item in scope.asset_classes} == (
        ALL_CLASSIFIED_ASSET_CLASSES
    )
    assert CandidateAssetClass.OTHER not in {
        item.asset_class for item in scope.asset_classes
    }
    assert scope.long_only is True
    assert scope.maximum_gross_leverage == 1.0
    assert scope.real_money_authorized is False
    assert scope.unclassified_assets_prohibited is True


def test_rehearsal_fills_all_thirteen_classified_asset_classes(
    tmp_path: Path,
) -> None:
    report = run_all_markets_paper_rehearsal(
        evaluated_at=AS_OF,
        working_directory=tmp_path,
    )
    expected = tuple(
        sorted(item.value for item in ALL_CLASSIFIED_ASSET_CLASSES)
    )

    assert len(expected) == 13
    assert report.complete is True
    assert report.expected_asset_classes == expected
    assert report.filled_asset_classes == expected
    assert report.fill_count >= 13
    assert report.ending_cash >= 0.0
    assert abs(report.reconciliation_difference) < 1e-7
    assert report.to_dict()["real_money_authorized"] is False


def test_universal_availability_requires_scope_policy_and_rehearsal(
    tmp_path: Path,
) -> None:
    scope = load_universal_paper_asset_class_scope(SCOPE)
    rehearsal = run_all_markets_paper_rehearsal(
        evaluated_at=AS_OF,
        working_directory=tmp_path,
    )
    report = assess_universal_paper_availability(
        scope=scope,
        evaluated_at=AS_OF,
        rehearsed_asset_classes=rehearsal.filled_asset_classes,
    )

    expected = tuple(
        sorted(item.value for item in ALL_CLASSIFIED_ASSET_CLASSES)
    )
    assert report.available is True
    assert report.expected_asset_classes == expected
    assert report.declared_asset_classes == expected
    assert report.policy_ready_asset_classes == expected
    assert report.rehearsed_asset_classes == expected
    assert report.blockers == ()
    assert report.to_dict()["provider_backed_live_paper_ready"] is False


def test_missing_asset_class_fails_closed() -> None:
    scope = load_universal_paper_asset_class_scope(SCOPE)
    reduced = replace(scope, asset_classes=scope.asset_classes[:-1])
    expected = tuple(
        sorted(item.value for item in ALL_CLASSIFIED_ASSET_CLASSES)
    )
    report = assess_universal_paper_availability(
        scope=reduced,
        evaluated_at=AS_OF,
        rehearsed_asset_classes=expected,
    )

    assert report.available is False
    assert any("does not exactly cover" in item for item in report.blockers)


def test_cli_persists_credential_safe_universal_report(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "universal.json"
    result = main(
        (
            "--scope",
            str(SCOPE),
            "--evaluated-at",
            AS_OF.isoformat(),
            "--working-directory",
            str(tmp_path / "rehearsal"),
            "--output",
            str(output),
            "--require-available",
        )
    )
    payload = json.loads(capsys.readouterr().out)
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert result == 0
    assert payload == persisted
    assert payload["available"] is True
    assert payload["rehearsal"]["all_classified_asset_classes_covered"] is True
    assert payload["live_order_routing_authorized"] is False
    assert payload["real_money_authorized"] is False
