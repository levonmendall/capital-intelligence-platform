from pathlib import Path

path = Path("scripts/materialize_phase7_governance_learning.py")
text = path.read_text(encoding="utf-8")

old_import = '''    replace_once(
        "opportunity/engine.py",
        """from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile
""",
        """from cio.policy_authority import CanonicalDecisionPolicyAuthority
from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile
""",
    )
'''
new_import = '''    replace_once(
        "opportunity/engine.py",
        """from cio.policy_matrix import DecisionPolicyMatrix
""",
        """from cio.policy_authority import CanonicalDecisionPolicyAuthority
from cio.policy_matrix import DecisionPolicyMatrix
""",
    )
'''
if text.count(old_import) != 1:
    raise SystemExit("Phase 7 opportunity import repair did not find exactly one target")
text = text.replace(old_import, new_import, 1)

old_timestamp_check = '''                _aware(value, field_name=field_name)
                if value > self.decided_at:
                    raise ValueError(
                        f"{field_name} cannot follow the prior decision timestamp"
                    )
'''
new_timestamp_check = '''                _aware(value, field_name=field_name)
'''
if text.count(old_timestamp_check) != 1:
    raise SystemExit("Phase 7 outage timestamp repair did not find exactly one target")
text = text.replace(old_timestamp_check, new_timestamp_check, 1)

no_op = '''    replace_once(
        "cio/service.py",
        """            policy_matrix_version=self.policy_matrix.version,
        )
""",
        """            policy_matrix_version=self.policy_matrix.version,
        )
""",
    )
'''
if text.count(no_op) != 1:
    raise SystemExit("Phase 7 no-op removal did not find exactly one target")
text = text.replace(no_op, "", 1)

path.write_text(text, encoding="utf-8")
