from __future__ import annotations

from pathlib import Path


# Phase 2 intentionally patches both PortfolioAsset and ConstructionIntent.
path = Path(".decision-upgrade/phase2.py")
text = path.read_text()
old = '''replace_one(
    "portfolio/construction_models.py",
    "    instrument_identifier: str | None = None\\n\\n    def __post_init__(self) -> None:\\n",
    "    instrument_identifier: str | None = None\\n    uses_derivatives: bool = False\\n    derivative_lifecycle: DerivativeLifecycleProfile | None = None\\n\\n    def __post_init__(self) -> None:\\n",
)
'''
new = '''text = Path("portfolio/construction_models.py").read_text()
field_needle = "    instrument_identifier: str | None = None\\n\\n    def __post_init__(self) -> None:\\n"
field_replacement = "    instrument_identifier: str | None = None\\n    uses_derivatives: bool = False\\n    derivative_lifecycle: DerivativeLifecycleProfile | None = None\\n\\n    def __post_init__(self) -> None:\\n"
if text.count(field_needle) != 2:
    raise RuntimeError("construction_models.py: expected two derivative field insertion points")
Path("portfolio/construction_models.py").write_text(text.replace(field_needle, field_replacement))
'''
if text.count(old) != 1:
    raise RuntimeError("phase2.py: expected one ambiguous derivative-field transformer")
path.write_text(text.replace(old, new))

# State continuity belongs in the canonical scheduled executor, not the
# production evidence assembler.
path = Path(".decision-upgrade/phase1.py")
text = path.read_text()
old = '''# Scheduled production path activates journal-derived state continuity.
for path in ("application/production_cio.py", "application/production_context.py"):
    replace_one(
        path,
        "        return self.cycle.run(\\n",
        "        prior_contexts = ()\\n        active_theses = ()\\n        if self.cycle.journal is not None:\\n            prior_contexts = self.cycle.journal.prior_decision_contexts(\\n                candidates, as_of=decision_time\\n            )\\n            active_theses = self.cycle.journal.active_theses(\\n                candidates, as_of=decision_time\\n            )\\n        return self.cycle.run(\\n",
    )
    replace_one(
        path,
        "            portfolio=portfolio,\\n            code_version=context.code_version,\\n",
        "            portfolio=portfolio,\\n            prior_decision_contexts=prior_contexts,\\n            active_theses=active_theses,\\n            code_version=context.code_version,\\n",
    ) if path.endswith("production_context.py") else replace_one(
        path,
        "            portfolio=context.portfolio,\\n            code_version=context.code_version,\\n",
        "            portfolio=context.portfolio,\\n            prior_decision_contexts=prior_contexts,\\n            active_theses=active_theses,\\n            code_version=context.code_version,\\n",
    )
'''
new = '''# Scheduled production path activates journal-derived state continuity.
replace_one(
    "application/production_cio.py",
    "        return self.cycle.run(\\n",
    "        prior_contexts = ()\\n        active_theses = ()\\n        if self.cycle.journal is not None:\\n            prior_contexts = self.cycle.journal.prior_decision_contexts(\\n                candidates, as_of=decision_time\\n            )\\n            active_theses = self.cycle.journal.active_theses(\\n                candidates, as_of=decision_time\\n            )\\n        return self.cycle.run(\\n",
)
replace_one(
    "application/production_cio.py",
    "            portfolio=context.portfolio,\\n            code_version=context.code_version,\\n",
    "            portfolio=context.portfolio,\\n            prior_decision_contexts=prior_contexts,\\n            active_theses=active_theses,\\n            code_version=context.code_version,\\n",
)
'''
if text.count(old) != 1:
    raise RuntimeError("phase1.py: expected one production-executor loop")
path.write_text(text.replace(old, new))

# Complete scenarios are enforced by the same canonical executor after phase 1
# has inserted the state-continuity block.
path = Path(".decision-upgrade/phase3.py")
text = path.read_text()
old = '''# Governed production must carry the complete common scenario set.
replace_one(
    "application/production_context.py",
    "        if governed_context:\\n            publication_identifiers = qualified_identifiers + rejected_identifiers\\n",
    "        if governed_context:\\n            if context.portfolio.scenario_set is None:\\n                raise RuntimeError(\\n                    \"governed production CIO context requires a complete portfolio scenario set\"\\n                )\\n            publication_identifiers = qualified_identifiers + rejected_identifiers\\n",
)
'''
new = '''# Governed production must carry the complete common scenario set.
replace_one(
    "application/production_cio.py",
    "        prior_contexts = ()\\n",
    "        if context.portfolio.scenario_set is None:\\n            raise RuntimeError(\\n                \"production CIO context requires a complete portfolio scenario set\"\\n            )\\n        prior_contexts = ()\\n",
)
'''
if text.count(old) != 1:
    raise RuntimeError("phase3.py: expected one stale production-context target")
path.write_text(text.replace(old, new))
