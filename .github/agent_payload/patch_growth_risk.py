from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "cio/robustness.py"
source = path.read_text(encoding="utf-8")

old = '''        policy_profile: DecisionPolicyProfile | None = None,
    ) -> float:
        """Return the largest target that passes the complete robustness policy.

        The search evaluates the final candidate distribution at the actual target
        weight.  It is intentionally conservative: when even the smallest feasible
        test weight fails, no positive robust allocation is returned.
        """
'''
new = '''        policy_profile: DecisionPolicyProfile | None = None,
        allow_soft_failures: bool = False,
    ) -> float:
        """Return the largest target that passes the applicable robustness policy.

        Full acquisitions require every robustness control. Participation and
        exploration may treat edge, stress, uncertainty, and probability-of-loss
        shortfalls as sizing inputs. Scenario integrity and worst-case portfolio
        loss remain hard portfolio-survival constraints.
        """
'''
if source.count(old) != 1:
    raise RuntimeError("robust sizing signature anchor changed")
source = source.replace(old, new, 1)

old = '''        if self.assess(
            candidate,
            alternative_return=alternative_return,
            position_weight=cap,
            policy_profile=policy_profile,
        ).passed:
            return round(cap, 8)

        floor_weight = min(self.policy.minimum_reference_weight, cap)
        if not self.assess(
            candidate,
            alternative_return=alternative_return,
            position_weight=floor_weight,
            policy_profile=policy_profile,
        ).passed:
            return 0.0
'''
new = '''        def accepted(weight: float) -> bool:
            assessment = self.assess(
                candidate,
                alternative_return=alternative_return,
                position_weight=weight,
                policy_profile=policy_profile,
            )
            if assessment.passed:
                return True
            if not allow_soft_failures:
                return False
            hard_markers = (
                "scenario ordering",
                "non-positive portfolio wealth",
                "inconsistent with the disclosed scenarios",
                "worst-case portfolio loss",
            )
            return not any(
                any(marker in reason for marker in hard_markers)
                for reason in assessment.reasons
            )

        if accepted(cap):
            return round(cap, 8)

        floor_weight = min(self.policy.minimum_reference_weight, cap)
        if not accepted(floor_weight):
            return 0.0
'''
if source.count(old) != 1:
    raise RuntimeError("robust sizing decision anchor changed")
source = source.replace(old, new, 1)

old = '''            if self.assess(
                candidate,
                alternative_return=alternative_return,
                position_weight=middle,
                policy_profile=policy_profile,
            ).passed:
'''
if source.count(old) != 1:
    raise RuntimeError("robust midpoint anchor changed")
source = source.replace(old, '''            if accepted(middle):
''', 1)

old = '''            if self.assess(
                candidate,
                alternative_return=alternative_return,
                position_weight=supported,
                policy_profile=policy_profile,
            ).passed:
'''
if source.count(old) != 1:
    raise RuntimeError("robust final anchor changed")
source = source.replace(old, '''            if accepted(supported):
''', 1)

path.write_text(source, encoding="utf-8")
print("growth risk sizing patched")
