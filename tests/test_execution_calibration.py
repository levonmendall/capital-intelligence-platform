from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from operations.execution_calibration import (
    ExecutionCalibrationEvaluator,
    ExecutionCalibrationPolicy,
    ExecutionCalibrationSample,
    ExecutionCalibrationState,
    ExecutionSide,
)
from run_execution_calibration import main as calibration_main

NOW = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)


def _samples(*, stale: bool = False, error_bps: float = 5.0):
    result = []
    asset_classes = ("equity", "fixed_income", "crypto")
    for index in range(12):
        midpoint = 100.0 + index
        bid = midpoint - 0.05
        ask = midpoint + 0.05
        side = ExecutionSide.BUY if index % 2 == 0 else ExecutionSide.SELL
        benchmark = ask if side is ExecutionSide.BUY else bid
        direction = 1.0 if side is ExecutionSide.BUY else -1.0
        modeled = benchmark + direction * midpoint * error_bps / 10_000.0
        result.append(
            ExecutionCalibrationSample(
                identifier=f"calibration-sample:{index}",
                instrument_identifier=f"instrument:{index}",
                asset_class=asset_classes[index % len(asset_classes)],
                venue=f"venue:{index % 3}",
                provider="independent-quote-provider",
                observed_at=NOW,
                modeled_at=NOW + timedelta(seconds=120 if stale and index == 0 else 10),
                side=side,
                bid=bid,
                ask=ask,
                benchmark_fill_price=benchmark,
                modeled_fill_price=modeled,
                source_identifier=f"quote-evidence:{index}",
            )
        )
    return tuple(result)


def test_representative_calibration_passes() -> None:
    report = ExecutionCalibrationEvaluator().evaluate(
        identifier="execution-calibration:test",
        execution_policy_version="multi-asset-paper-execution.v1",
        samples=_samples(),
        evaluated_at=NOW + timedelta(minutes=5),
    )

    assert report.state is ExecutionCalibrationState.PASSED
    assert report.sample_count == 12
    assert report.asset_class_count == 3
    assert report.p95_absolute_error_bps <= 5.000001
    assert report.to_dict()["paper_test_authorized"] is False


def test_stale_or_miscalibrated_samples_block() -> None:
    policy = ExecutionCalibrationPolicy(maximum_single_sample_error_bps=60.0)
    report = ExecutionCalibrationEvaluator(policy).evaluate(
        identifier="execution-calibration:blocked",
        execution_policy_version="multi-asset-paper-execution.v1",
        samples=_samples(stale=True, error_bps=30.0),
        evaluated_at=NOW + timedelta(minutes=5),
    )

    assert report.state is ExecutionCalibrationState.BLOCKED
    joined = " ".join(report.blockers)
    assert "stale_sample_count=1" in joined
    assert "p95_absolute_error_bps" in joined


def test_calibration_cli_writes_machine_readable_report(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "calibration-input.json"
    source.write_text(
        json.dumps(
            {
                "identifier": "execution-calibration:cli",
                "execution_policy_version": "multi-asset-paper-execution.v1",
                "samples": [sample.to_dict() for sample in _samples()],
                "schema_version": "paper-execution-calibration-input.v1",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "calibration-report.json"

    exit_code = calibration_main(
        (
            "--input",
            str(source),
            "--evaluated-at",
            (NOW + timedelta(minutes=5)).isoformat(),
            "--output",
            str(output),
            "--require-passed",
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["state"] == "passed"
    assert payload["execution_cost_error_bps"] <= 5.000001
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True
