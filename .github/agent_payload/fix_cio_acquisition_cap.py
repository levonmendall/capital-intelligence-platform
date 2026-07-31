from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "cio/service.py"
source = path.read_text(encoding="utf-8")
old = '''        robust_cap = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=min(
                feasible_cap,
                ensemble.maximum_target_weight or feasible_cap,
            ),
            policy_profile=profile,
            allow_soft_failures=progressive_lane,
        )
'''
new = '''        growth_cap = (
            min(feasible_cap, ensemble.maximum_target_weight or feasible_cap)
            if progressive_lane
            else feasible_cap
        )
        robust_cap = self.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=growth_cap,
            policy_profile=profile,
            allow_soft_failures=progressive_lane,
        )
'''
if source.count(old) != 1:
    raise RuntimeError("acquisition cap anchor changed")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
print("preserved full-conviction acquisition cap")
