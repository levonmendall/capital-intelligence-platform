from __future__ import annotations

from pathlib import Path

from governance import PaperTradingLaunchPolicy
from run_multi_asset_paper_execution import build_parser


def test_paper_access_has_no_launch_clearance_prerequisites() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--construction",
            "construction.json",
            "--profiles",
            "profiles.json",
            "--decision-identifier",
            "decision:test",
            "--session-provider",
            "module:session",
            "--quote-provider",
            "module:quotes",
            "--as-of",
            "2026-07-29T00:00:00+00:00",
        ]
    )
    assert args.baseline_identifier is None
    assert args.process_version is None
    assert args.code_version is None


def test_launch_policy_preserves_safety_limits_but_not_elapsed_delay() -> None:
    policy = PaperTradingLaunchPolicy()
    assert policy.minimum_burn_in_days == 0
    assert policy.maximum_drawdown_fraction == 0.20
    assert policy.maximum_single_batch_turnover == 0.35


def test_executor_no_longer_calls_combined_launch_authority() -> None:
    source = Path("run_multi_asset_paper_execution.py").read_text(encoding="utf-8")
    assert "require_combined_paper_execution_authorization" not in source
    assert '"launch_clearance_required": False' in source
    assert '"human_release_approval_required": False' in source
    assert '"runtime_activation_required": False' in source
