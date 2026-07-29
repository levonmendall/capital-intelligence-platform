from __future__ import annotations

import re
from pathlib import Path


def replace_one(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    file.write_text(text.replace(old, new))


def regex_one(path: str, pattern: str, replacement: str) -> None:
    file = Path(path)
    text = file.read_text()
    updated, count = re.subn(pattern, replacement, text, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}")
    file.write_text(updated)


replace_one(
    "application/cio_cycle.py",
    "    ConstructionIntent,\n    ConstructionStatus,\n",
    "    ConstructionIntent,\n    ConstructionMode,\n    ConstructionStatus,\n",
)
replace_one(
    "application/cio_cycle.py",
    "from reporting.daily_cio import DailyCIOBriefing, DailyCIOBriefingBuilder\nfrom thesis import LivingThesis\n",
    "from portfolio.derivative_lifecycle import DerivativeLifecycleProfile\nfrom portfolio.scenario_authority import (\n    GovernedPortfolioScenarioSet,\n    PortfolioScenarioAuthority,\n)\nfrom reporting.daily_cio import DailyCIOBriefing, DailyCIOBriefingBuilder\nfrom thesis import (\n    LivingThesis,\n    StructuredThesisConditionScorer,\n    ThesisCondition,\n)\n",
)
replace_one(
    "application/cio_cycle.py",
    "    correlation_bucket: str\n\n    def __post_init__(self) -> None:\n",
    "    correlation_bucket: str\n    thesis_conditions: tuple[ThesisCondition, ...] = ()\n    invalidation_conditions_structured: tuple[ThesisCondition, ...] = ()\n    derivative_lifecycle: DerivativeLifecycleProfile | None = None\n\n    def __post_init__(self) -> None:\n",
)
replace_one(
    "application/cio_cycle.py",
    "        object.__setattr__(\n            self,\n            \"factor_loadings\",\n            _loading_tuple(self.factor_loadings),\n        )\n",
    "        object.__setattr__(\n            self,\n            \"factor_loadings\",\n            _loading_tuple(self.factor_loadings),\n        )\n        for field_name in (\n            \"thesis_conditions\",\n            \"invalidation_conditions_structured\",\n        ):\n            values = getattr(self, field_name)\n            if not isinstance(values, tuple) or not all(\n                isinstance(item, ThesisCondition) for item in values\n            ):\n                raise TypeError(f\"{field_name} must contain ThesisCondition values\")\n        if self.derivative_lifecycle is not None and not isinstance(\n            self.derivative_lifecycle, DerivativeLifecycleProfile\n        ):\n            raise TypeError(\n                \"derivative_lifecycle must be DerivativeLifecycleProfile or None\"\n            )\n",
)
replace_one(
    "application/cio_cycle.py",
    "    eligible_universe_publication_identifier: str | None = None\n\n    def __post_init__(self) -> None:\n",
    "    eligible_universe_publication_identifier: str | None = None\n    scenario_set: GovernedPortfolioScenarioSet | None = None\n\n    def __post_init__(self) -> None:\n",
)
replace_one(
    "application/cio_cycle.py",
    "        if self.eligible_universe_publication_identifier is not None:\n",
    "        if self.scenario_set is not None:\n            if not isinstance(self.scenario_set, GovernedPortfolioScenarioSet):\n                raise TypeError(\"scenario_set must be GovernedPortfolioScenarioSet or None\")\n            if self.scenario_set.as_of > self.as_of:\n                raise ValueError(\"portfolio scenario set cannot be from the future\")\n        if self.eligible_universe_publication_identifier is not None:\n",
)
replace_one(
    "application/cio_cycle.py",
    "        scenarios: tuple[PortfolioScenario, ...] = (),\n    ) -> PortfolioConstructionRequest:\n        return PortfolioConstructionRequest(\n",
    "        scenarios: tuple[PortfolioScenario, ...] = (),\n        mode: ConstructionMode = ConstructionMode.NORMAL,\n    ) -> PortfolioConstructionRequest:\n        scenario_identifier = None\n        if not scenarios and self.scenario_set is not None:\n            symbols = tuple(\n                sorted(\n                    {item.symbol for item in self.positions}\n                    | {item.symbol for item in intents}\n                )\n            )\n            scenarios = PortfolioScenarioAuthority().authorize(\n                self.scenario_set,\n                as_of=self.as_of,\n                symbols=symbols,\n            )\n            scenario_identifier = self.scenario_set.identifier\n        return PortfolioConstructionRequest(\n",
)
replace_one(
    "application/cio_cycle.py",
    "            scenarios=scenarios,\n        )\n",
    "            scenarios=scenarios,\n            mode=mode,\n            scenario_set_identifier=scenario_identifier,\n        )\n",
)

replace_one(
    "application/cio_cycle.py",
    "            thesis = cls._text_clarity(\n                candidate.primary_catalysts + candidate.critical_assumptions\n            )\n            invalidation = cls._text_clarity(candidate.invalidation_conditions)\n",
    "            scorer = StructuredThesisConditionScorer()\n            thesis = scorer.score(profile.thesis_conditions).score\n            invalidation = scorer.score(\n                profile.invalidation_conditions_structured\n            ).score\n",
)
regex_one(
    "application/cio_cycle.py",
    r"    @staticmethod\n    def _text_clarity\(.*?\n    def _capture_evaluation_snapshots\(",
    "    def _capture_evaluation_snapshots(",
)

replace_one(
    "application/cio_cycle.py",
    "                    correlation_bucket=profile.correlation_bucket,\n                    priority_rank=priority_rank,\n",
    "                    correlation_bucket=profile.correlation_bucket,\n                    priority_rank=priority_rank,\n                    derivative_lifecycle=profile.derivative_lifecycle,\n",
)
replace_one(
    "application/cio_cycle.py",
    "        scenarios = self._joint_portfolio_scenarios(\n            decisions=decisions,\n            ranked_by_candidate=ranked_by_candidate,\n            portfolio=portfolio,\n        )\n        return self.construction_engine.construct(\n            portfolio.request(\n                identifier=f\"construction:{cycle_identifier}\",\n                intents=tuple(intents),\n                scenarios=scenarios,\n            )\n        )\n",
    "        mode = (\n            ConstructionMode.EMERGENCY_DE_RISKING\n            if any(\n                item.action in {CIOAction.REDUCE, CIOAction.EXIT}\n                and (item.evidence_vetoes or item.expected_return <= -0.05)\n                for item in decisions\n            )\n            else ConstructionMode.NORMAL\n        )\n        return self.construction_engine.construct(\n            portfolio.request(\n                identifier=f\"construction:{cycle_identifier}\",\n                intents=tuple(intents),\n                mode=mode,\n            )\n        )\n",
)
regex_one(
    "application/cio_cycle.py",
    r"    @staticmethod\n    def _joint_portfolio_scenarios\(.*?\n    def _create_theses\(",
    "    def _create_theses(",
)

replace_one(
    "application/production_cio.py",
    "        prior_contexts = ()\n",
    "        if context.portfolio.scenario_set is None:\n            raise RuntimeError(\n                \"production CIO context requires a complete portfolio scenario set\"\n            )\n        prior_contexts = ()\n",
)
