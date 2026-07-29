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


# Construction contracts: emergency mode, exact scenarios, derivative lifecycle.
replace_one(
    "portfolio/construction_models.py",
    "from cio import CIOAction, CIODecision, CandidateDecisionRecord\n",
    "from cio import CIOAction, CIODecision, CandidateDecisionRecord\nfrom portfolio.derivative_lifecycle import DerivativeLifecycleProfile\n",
)
replace_one(
    "portfolio/construction_models.py",
    "class TradeSide(str, Enum):\n",
    "class ConstructionMode(str, Enum):\n    NORMAL = \"normal\"\n    EMERGENCY_DE_RISKING = \"emergency_de_risking\"\n\n\nclass TradeSide(str, Enum):\n",
)
replace_one(
    "portfolio/construction_models.py",
    "    version: str = \"portfolio-construction.v3\"\n",
    "    version: str = \"portfolio-construction.v4\"\n",
)
replace_one(
    "portfolio/construction_models.py",
    "    maximum_total_cost_return: float = 0.005\n",
    "    maximum_total_cost_return: float = 0.005\n    emergency_maximum_turnover: float = 1.0\n    emergency_maximum_total_cost_return: float = 0.03\n",
)
replace_one(
    "portfolio/construction_models.py",
    "            \"maximum_total_cost_return\",\n",
    "            \"maximum_total_cost_return\",\n            \"emergency_maximum_turnover\",\n            \"emergency_maximum_total_cost_return\",\n",
)
replace_one(
    "portfolio/construction_models.py",
    "    instrument_identifier: str | None = None\n\n    def __post_init__(self) -> None:\n",
    "    instrument_identifier: str | None = None\n    uses_derivatives: bool = False\n    derivative_lifecycle: DerivativeLifecycleProfile | None = None\n\n    def __post_init__(self) -> None:\n",
)
# Applies to both PortfolioAsset and ConstructionIntent.
text = Path("portfolio/construction_models.py").read_text()
needle = '''        object.__setattr__(\n            self,\n            "instrument_identifier",\n            _optional_text(\n                self.instrument_identifier,\n                field_name="instrument_identifier",\n            ),\n        )\n'''
addition = needle + '''        if not isinstance(self.uses_derivatives, bool):\n            raise TypeError("uses_derivatives must be a bool")\n        if self.derivative_lifecycle is not None and not isinstance(\n            self.derivative_lifecycle, DerivativeLifecycleProfile\n        ):\n            raise TypeError(\n                "derivative_lifecycle must be DerivativeLifecycleProfile or None"\n            )\n        if not self.uses_derivatives and self.derivative_lifecycle is not None:\n            raise ValueError("non-derivative assets cannot carry derivative lifecycle data")\n'''
if text.count(needle) != 2:
    raise RuntimeError("construction_models.py: expected two instrument validation blocks")
Path("portfolio/construction_models.py").write_text(text.replace(needle, addition))
replace_one(
    "portfolio/construction_models.py",
    "        priority_rank: int,\n    ) -> \"ConstructionIntent\":\n",
    "        priority_rank: int,\n        derivative_lifecycle: DerivativeLifecycleProfile | None = None,\n    ) -> \"ConstructionIntent\":\n",
)
replace_one(
    "portfolio/construction_models.py",
    "            instrument_identifier=candidate.instrument.instrument_id,\n        )\n",
    "            instrument_identifier=candidate.instrument.instrument_id,\n            uses_derivatives=candidate.instrument.uses_derivatives,\n            derivative_lifecycle=derivative_lifecycle,\n        )\n",
)
replace_one(
    "portfolio/construction_models.py",
    "    def return_for(self, symbol: str, fallback: float) -> float:\n        resolved = symbol.strip().upper()\n        return next((value for name, value in self.asset_returns if name == resolved), fallback)\n",
    "    def return_for(self, symbol: str) -> float:\n        resolved = symbol.strip().upper()\n        value = next((item for name, item in self.asset_returns if name == resolved), None)\n        if value is None:\n            raise KeyError(f\"scenario {self.name} is missing {resolved}\")\n        return value\n",
)
replace_one(
    "portfolio/construction_models.py",
    "    scenarios: tuple[PortfolioScenario, ...] = ()\n",
    "    scenarios: tuple[PortfolioScenario, ...] = ()\n    mode: ConstructionMode = ConstructionMode.NORMAL\n    scenario_set_identifier: str | None = None\n",
)
replace_one(
    "portfolio/construction_models.py",
    "        if self.scenarios:\n            if abs(sum(item.probability for item in self.scenarios) - 1.0) > 0.000001:\n                raise ValueError(\"portfolio scenario probabilities must sum to 1.0\")\n            names = tuple(item.name for item in self.scenarios)\n            if len(names) != len(set(names)):\n                raise ValueError(\"portfolio scenario names must be unique\")\n",
    "        if self.scenarios:\n            if abs(sum(item.probability for item in self.scenarios) - 1.0) > 0.000001:\n                raise ValueError(\"portfolio scenario probabilities must sum to 1.0\")\n            names = tuple(item.name for item in self.scenarios)\n            if len(names) != len(set(names)):\n                raise ValueError(\"portfolio scenario names must be unique\")\n            expected_symbols = set(symbols) | set(intent_symbols)\n            for scenario in self.scenarios:\n                observed = {symbol for symbol, _ in scenario.asset_returns}\n                if observed != expected_symbols:\n                    missing = sorted(expected_symbols - observed)\n                    extra = sorted(observed - expected_symbols)\n                    raise ValueError(\n                        \"portfolio scenarios must exactly cover every position and intent; \"\n                        f\"missing={missing} extra={extra}\"\n                    )\n        if not isinstance(self.mode, ConstructionMode):\n            raise TypeError(\"mode must be ConstructionMode\")\n        object.__setattr__(\n            self,\n            \"scenario_set_identifier\",\n            _optional_text(self.scenario_set_identifier, field_name=\"scenario_set_identifier\"),\n        )\n",
)
replace_one(
    "portfolio/construction_models.py",
    "    scenario_metrics_after: PortfolioScenarioMetrics | None = None\n",
    "    scenario_metrics_after: PortfolioScenarioMetrics | None = None\n    mode: ConstructionMode = ConstructionMode.NORMAL\n    scenario_set_identifier: str | None = None\n    residual_exposures: tuple[tuple[str, float], ...] = ()\n",
)
replace_one(
    "portfolio/construction_models.py",
    "        if not isinstance(self.status, ConstructionStatus):\n            raise TypeError(\"status must be a ConstructionStatus\")\n",
    "        if not isinstance(self.status, ConstructionStatus):\n            raise TypeError(\"status must be a ConstructionStatus\")\n        if not isinstance(self.mode, ConstructionMode):\n            raise TypeError(\"mode must be ConstructionMode\")\n        object.__setattr__(\n            self,\n            \"scenario_set_identifier\",\n            _optional_text(self.scenario_set_identifier, field_name=\"scenario_set_identifier\"),\n        )\n        if not isinstance(self.residual_exposures, tuple):\n            raise TypeError(\"residual_exposures must be a tuple\")\n        residuals = tuple(\n            (\n                _required_text(symbol, field_name=\"residual symbol\").upper(),\n                _finite(weight, field_name=f\"residual exposure:{symbol}\", minimum=0.0, maximum=1.0),\n            )\n            for symbol, weight in self.residual_exposures\n        )\n        object.__setattr__(self, \"residual_exposures\", residuals)\n",
)

# Export the new construction mode and lifecycle contracts.
replace_one(
    "portfolio/construction_api.py",
    "    ConstructionIntent,\n    ConstructionStatus,\n",
    "    ConstructionIntent,\n    ConstructionMode,\n    ConstructionStatus,\n",
)
replace_one(
    "portfolio/construction_api.py",
    "    \"ConstructionIntent\",\n    \"ConstructionStatus\",\n",
    "    \"ConstructionIntent\",\n    \"ConstructionMode\",\n    \"ConstructionStatus\",\n",
)

# Engine enforces lifecycle controls, emergency soft limits, and no scenario fallback.
replace_one(
    "portfolio/construction_engine.py",
    "from portfolio.construction_models import (\n    ConstructionIntent,\n",
    "from portfolio.construction_models import (\n    ConstructionIntent,\n    ConstructionMode,\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "    TradeSide,\n)\n",
    "    TradeSide,\n)\nfrom portfolio.derivative_lifecycle import DerivativeLifecycleAuthority\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "        self.policy = policy or PortfolioConstructionPolicy()\n",
    "        self.policy = policy or PortfolioConstructionPolicy()\n        self.derivative_authority = DerivativeLifecycleAuthority()\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "        self._apply_optimized_positive_allocations(\n            request=request,\n            target=target,\n            assets=assets,\n            intents=intents,\n            reasons=reasons,\n            funding_for=funding_for,\n            blocks=blocks,\n        )\n",
    "        emergency_residuals = self._requested_reduction_residuals(\n            request=request, target=target\n        )\n        if request.mode is ConstructionMode.EMERGENCY_DE_RISKING and emergency_residuals:\n            blocks.append(\n                \"positive allocations are prohibited while emergency reductions remain incomplete\"\n            )\n        else:\n            self._apply_optimized_positive_allocations(\n                request=request,\n                target=target,\n                assets=assets,\n                intents=intents,\n                reasons=reasons,\n                funding_for=funding_for,\n                blocks=blocks,\n            )\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "            scenario_metrics_after=scenario_after,\n        )\n",
    "            scenario_metrics_after=scenario_after,\n            mode=request.mode,\n            scenario_set_identifier=request.scenario_set_identifier,\n            residual_exposures=self._requested_reduction_residuals(\n                request=request, target=target\n            ),\n        )\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "            value = scenario.return_for(symbol, asset.expected_return)\n",
    "            value = scenario.return_for(symbol)\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "            acquisition_cost = (\n                intent.transaction_cost_bps + intent.slippage_bps\n            ) / 10_000\n",
    "            if intent.uses_derivatives:\n                lifecycle = self.derivative_authority.assess(\n                    intent.derivative_lifecycle,\n                    instrument_identifier=(intent.instrument_identifier or intent.symbol),\n                    as_of=request.as_of,\n                )\n                if not lifecycle.authorized:\n                    blocks.append(\n                        f\"{intent.symbol} remains analysis-only: \"\n                        + \"; \".join(lifecycle.reasons)\n                    )\n                    continue\n            acquisition_cost = (\n                intent.transaction_cost_bps + intent.slippage_bps\n            ) / 10_000\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "        if self._turnover(request, target) > self.policy.maximum_turnover + _EPSILON:\n            return False\n        if self._cost(request, target, assets) > self.policy.maximum_total_cost_return + _EPSILON:\n            return False\n",
    "        turnover_limit = (\n            self.policy.emergency_maximum_turnover\n            if request.mode is ConstructionMode.EMERGENCY_DE_RISKING\n            else self.policy.maximum_turnover\n        )\n        cost_limit = (\n            self.policy.emergency_maximum_total_cost_return\n            if request.mode is ConstructionMode.EMERGENCY_DE_RISKING\n            else self.policy.maximum_total_cost_return\n        )\n        if self._turnover(request, target) > turnover_limit + _EPSILON:\n            return False\n        if self._cost(request, target, assets) > cost_limit + _EPSILON:\n            return False\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "        checks: list[ConstraintCheck] = [\n",
    "        turnover_limit = (\n            self.policy.emergency_maximum_turnover\n            if request.mode is ConstructionMode.EMERGENCY_DE_RISKING\n            else self.policy.maximum_turnover\n        )\n        cost_limit = (\n            self.policy.emergency_maximum_total_cost_return\n            if request.mode is ConstructionMode.EMERGENCY_DE_RISKING\n            else self.policy.maximum_total_cost_return\n        )\n        checks: list[ConstraintCheck] = [\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "                satisfied=turnover <= self.policy.maximum_turnover + _EPSILON,\n                value=turnover,\n                limit=self.policy.maximum_turnover,\n",
    "                satisfied=turnover <= turnover_limit + _EPSILON,\n                value=turnover,\n                limit=turnover_limit,\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "                    f\"{self.policy.maximum_turnover:.2%}\"\n",
    "                    f\"{turnover_limit:.2%}\"\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "                satisfied=cost <= self.policy.maximum_total_cost_return + _EPSILON,\n                value=cost,\n                limit=self.policy.maximum_total_cost_return,\n",
    "                satisfied=cost <= cost_limit + _EPSILON,\n                value=cost,\n                limit=cost_limit,\n",
)
replace_one(
    "portfolio/construction_engine.py",
    "                    f\"{self.policy.maximum_total_cost_return:.2%}\"\n",
    "                    f\"{cost_limit:.2%}\"\n",
)
residual_helper = '''\n    @staticmethod\n    def _requested_reduction_residuals(\n        *,\n        request: PortfolioConstructionRequest,\n        target: dict[str, float],\n    ) -> tuple[tuple[str, float], ...]:\n        residuals: list[tuple[str, float]] = []\n        for intent in request.intents:\n            if intent.action not in {CIOAction.REDUCE, CIOAction.EXIT}:\n                continue\n            requested = intent.requested_target_weight or 0.0\n            actual = target.get(intent.symbol, 0.0)\n            if actual > requested + _EPSILON:\n                residuals.append((intent.symbol, round(actual - requested, 8)))\n        return tuple(sorted(residuals))\n\n'''
replace_one(
    "portfolio/construction_engine.py",
    "    def _is_feasible(\n",
    residual_helper + "    def _is_feasible(\n",
)
