from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 match, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "cio/policy_matrix.py",
    "The matrix centralizes the candidate-specific hurdles used by qualification,\n"
    "robustness, CIO synthesis, persistence, and final sizing. Execution wrappers do\n"
    "not dilute the risk classification of the economic exposure they represent: the\n"
    "resolved profile always combines the wrapper and exposure profiles using the\n"
    "stricter requirement for every control.\n",
    "The matrix centralizes candidate-specific acquisition and sizing controls. Hard\n"
    "evidence, liquidity, downside, execution, and lineage failures remain vetoes;\n"
    "ordinary uncertainty primarily reduces stage and size. Economic exposure governs\n"
    "risk while the execution wrapper contributes its tighter position ceiling.\n",
)
replace_once(
    "cio/policy_matrix.py",
    '    version = "decision-policy-matrix.v3"\n',
    '    version = "decision-policy-matrix.v4-growth"\n',
)
replace_once(
    "cio/policy_matrix.py",
    '''    _STANDARD = DecisionPolicyProfile(
        identifier="standard-intermediate",
        minimum_net_expected_return=0.05,
        minimum_opportunity_edge=0.01,
        minimum_probability_of_success=0.55,
        maximum_expected_downside=-0.35,
        maximum_position_weight=0.10,
        minimum_robust_edge=0.005,
        maximum_probability_of_loss=0.45,
        minimum_worst_case_portfolio_return=-0.05,
        entry_persistence_cycles=2,
        increase_persistence_cycles=2,
        reduce_persistence_cycles=2,
        cooldown_days=5,
        forecast_durability_floor=0.50,
        annualization_cap=0.60,
    )
''',
    '''    _STANDARD = DecisionPolicyProfile(
        identifier="standard-intermediate",
        minimum_net_expected_return=0.03,
        minimum_opportunity_edge=0.005,
        minimum_probability_of_success=0.52,
        maximum_expected_downside=-0.45,
        maximum_position_weight=0.12,
        minimum_robust_edge=0.0025,
        maximum_probability_of_loss=0.50,
        minimum_worst_case_portfolio_return=-0.06,
        entry_persistence_cycles=1,
        increase_persistence_cycles=2,
        reduce_persistence_cycles=2,
        cooldown_days=3,
        forecast_durability_floor=0.45,
        annualization_cap=0.70,
    )
''',
)
replace_once(
    "cio/policy_matrix.py",
    '''        return replace(
            cls._STANDARD,
            identifier="direct-common-equity-exploratory",
            minimum_net_expected_return=0.04,
            minimum_opportunity_edge=0.0025,
            minimum_probability_of_success=0.52,
            maximum_expected_downside=-0.55,
            maximum_position_weight=0.01,
            minimum_robust_edge=0.001,
            maximum_probability_of_loss=0.48,
            minimum_worst_case_portfolio_return=-0.01,
            entry_persistence_cycles=1,
            increase_persistence_cycles=2,
            reduce_persistence_cycles=2,
            cooldown_days=3,
            forecast_durability_floor=0.45,
            annualization_cap=0.60,
        )
''',
    '''        return replace(
            cls._STANDARD,
            identifier="direct-common-equity-exploratory",
            minimum_net_expected_return=0.02,
            minimum_opportunity_edge=0.0,
            minimum_probability_of_success=0.48,
            maximum_expected_downside=-0.60,
            maximum_position_weight=0.01,
            minimum_robust_edge=0.0,
            maximum_probability_of_loss=0.55,
            minimum_worst_case_portfolio_return=-0.0125,
            entry_persistence_cycles=1,
            increase_persistence_cycles=1,
            reduce_persistence_cycles=2,
            cooldown_days=1,
            forecast_durability_floor=0.40,
            annualization_cap=0.70,
        )
''',
)
replace_once(
    "cio/policy_matrix.py",
    '''            return replace(
                cls._STANDARD,
                identifier="diversified-liquid-intermediate",
                minimum_net_expected_return=0.04,
                minimum_opportunity_edge=0.008,
                minimum_probability_of_success=0.54,
                maximum_expected_downside=-0.25,
                maximum_position_weight=0.12,
                minimum_robust_edge=0.004,
                maximum_probability_of_loss=0.43,
                minimum_worst_case_portfolio_return=-0.045,
            )
''',
    '''            return replace(
                cls._STANDARD,
                identifier="diversified-liquid-intermediate",
                minimum_net_expected_return=0.02,
                minimum_opportunity_edge=0.003,
                minimum_probability_of_success=0.51,
                maximum_expected_downside=-0.35,
                maximum_position_weight=0.20,
                minimum_robust_edge=0.001,
                maximum_probability_of_loss=0.50,
                minimum_worst_case_portfolio_return=-0.06,
            )
''',
)
replace_once(
    "cio/policy_matrix.py",
    '''            return replace(
                cls._STANDARD,
                identifier="speculative-intermediate",
                minimum_net_expected_return=0.10,
                minimum_opportunity_edge=0.03,
                minimum_probability_of_success=0.62,
                maximum_expected_downside=-0.60,
                maximum_position_weight=0.05,
                minimum_robust_edge=0.02,
                maximum_probability_of_loss=0.35,
                minimum_worst_case_portfolio_return=-0.035,
                entry_persistence_cycles=3,
                increase_persistence_cycles=3,
                forecast_durability_floor=0.65,
                annualization_cap=0.40,
            )
''',
    '''            return replace(
                cls._STANDARD,
                identifier="speculative-intermediate",
                minimum_net_expected_return=0.06,
                minimum_opportunity_edge=0.015,
                minimum_probability_of_success=0.56,
                maximum_expected_downside=-0.65,
                maximum_position_weight=0.05,
                minimum_robust_edge=0.008,
                maximum_probability_of_loss=0.42,
                minimum_worst_case_portfolio_return=-0.04,
                entry_persistence_cycles=2,
                increase_persistence_cycles=2,
                forecast_durability_floor=0.55,
                annualization_cap=0.50,
            )
''',
)
replace_once(
    "cio/policy_matrix.py",
    '''            return replace(
                cls._STANDARD,
                identifier="nonlinear-derivative-intermediate",
                minimum_net_expected_return=0.12,
                minimum_opportunity_edge=0.04,
                minimum_probability_of_success=0.65,
                maximum_expected_downside=-1.0,
                maximum_position_weight=0.03,
                minimum_robust_edge=0.025,
                maximum_probability_of_loss=0.32,
                minimum_worst_case_portfolio_return=-0.03,
                entry_persistence_cycles=3,
                increase_persistence_cycles=3,
                forecast_durability_floor=0.70,
                annualization_cap=0.35,
            )
''',
    '''            return replace(
                cls._STANDARD,
                identifier="nonlinear-derivative-intermediate",
                minimum_net_expected_return=0.08,
                minimum_opportunity_edge=0.02,
                minimum_probability_of_success=0.58,
                maximum_expected_downside=-1.0,
                maximum_position_weight=0.03,
                minimum_robust_edge=0.012,
                maximum_probability_of_loss=0.40,
                minimum_worst_case_portfolio_return=-0.035,
                entry_persistence_cycles=2,
                increase_persistence_cycles=2,
                forecast_durability_floor=0.60,
                annualization_cap=0.45,
            )
''',
)
replace_once(
    "cio/policy_matrix.py",
    '''            return replace(
                profile,
                identifier=f"{profile.identifier}-tactical",
                minimum_net_expected_return=profile.minimum_net_expected_return * 1.25,
                minimum_opportunity_edge=profile.minimum_opportunity_edge * 1.50,
                minimum_probability_of_success=min(
                    0.80, profile.minimum_probability_of_success + 0.05
                ),
                maximum_position_weight=profile.maximum_position_weight * 0.75,
                entry_persistence_cycles=profile.entry_persistence_cycles + 1,
                increase_persistence_cycles=profile.increase_persistence_cycles + 1,
                forecast_durability_floor=max(profile.forecast_durability_floor, 0.70),
                annualization_cap=min(profile.annualization_cap, 0.35),
            )
''',
    '''            return replace(
                profile,
                identifier=f"{profile.identifier}-tactical",
                minimum_net_expected_return=profile.minimum_net_expected_return * 1.10,
                minimum_opportunity_edge=profile.minimum_opportunity_edge * 1.20,
                minimum_probability_of_success=min(
                    0.75, profile.minimum_probability_of_success + 0.02
                ),
                maximum_position_weight=profile.maximum_position_weight * 0.85,
                forecast_durability_floor=max(profile.forecast_durability_floor, 0.60),
                annualization_cap=min(profile.annualization_cap, 0.45),
            )
''',
)
print("aggressive compounding policy matrix patched")
