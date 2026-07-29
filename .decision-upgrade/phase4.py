from __future__ import annotations

from pathlib import Path


def replace_one(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    file.write_text(text.replace(old, new))


# Continuous distribution scoring and correct action/inaction confidence calibration.
replace_one(
    "evaluation/point_in_time.py",
    "    scenario_log_score: float = 0.0\n    decision_confidence_brier_score: float = 0.0\n",
    "    scenario_log_score: float = 0.0\n    scenario_crps: float = 0.0\n    decision_confidence_brier_score: float = 0.0\n",
)
replace_one(
    "evaluation/point_in_time.py",
    "            \"scenario_log_score\",\n            \"sizing_efficiency\",\n",
    "            \"scenario_log_score\",\n            \"scenario_crps\",\n            \"sizing_efficiency\",\n",
)
replace_one(
    "evaluation/point_in_time.py",
    "            \"scenario_log_score\": self.scenario_log_score,\n            \"decision_confidence_brier_score\": self.decision_confidence_brier_score,\n",
    "            \"scenario_log_score\": self.scenario_log_score,\n            \"scenario_crps\": self.scenario_crps,\n            \"decision_confidence_brier_score\": self.decision_confidence_brier_score,\n",
)
replace_one(
    "evaluation/point_in_time.py",
    "        scenario_log_score = 0.0\n        if snapshot.reconciled_outcomes:\n            realized_candidate = realized.decision_to_horizon_return\n            closest = min(\n                snapshot.reconciled_outcomes,\n                key=lambda item: abs(item.total_return - realized_candidate),\n            )\n            scenario_log_score = -log(max(closest.probability, 1e-12))\n",
    "        scenario_log_score = 0.0\n        scenario_crps = 0.0\n        if snapshot.reconciled_outcomes:\n            realized_candidate = realized.decision_to_horizon_return\n            closest = min(\n                snapshot.reconciled_outcomes,\n                key=lambda item: abs(item.total_return - realized_candidate),\n            )\n            scenario_log_score = -log(max(closest.probability, 1e-12))\n            first_moment = sum(\n                item.probability * abs(item.total_return - realized_candidate)\n                for item in snapshot.reconciled_outcomes\n            )\n            pairwise = sum(\n                left.probability\n                * right.probability\n                * abs(left.total_return - right.total_return)\n                for left in snapshot.reconciled_outcomes\n                for right in snapshot.reconciled_outcomes\n            )\n            scenario_crps = first_moment - 0.5 * pairwise\n",
)
replace_one(
    "evaluation/point_in_time.py",
    "            scenario_log_score=scenario_log_score,\n            decision_confidence_brier_score=decision_brier,\n",
    "            scenario_log_score=scenario_log_score,\n            scenario_crps=scenario_crps,\n            decision_confidence_brier_score=decision_brier,\n",
)
replace_one(
    "evaluation/point_in_time.py",
    "            success = (\n                1.0\n                if evaluation.outcome is EvaluationOutcome.VALUE_ADDED\n                else 0.0\n            )\n",
    "            success = (\n                1.0\n                if evaluation.outcome\n                in {\n                    EvaluationOutcome.VALUE_ADDED,\n                    EvaluationOutcome.MATCHED_ALTERNATIVE,\n                    EvaluationOutcome.CORRECT_ABSTENTION,\n                    EvaluationOutcome.AVOIDED_LOSS,\n                    EvaluationOutcome.INSUFFICIENT_EVIDENCE_CONFIRMED,\n                }\n                else 0.0\n            )\n",
)
replace_one(
    "evaluation/point_in_time.py",
    "                    evaluation.confidence_brier_score,\n",
    "                    evaluation.decision_confidence_brier_score,\n",
)

# Canonical exports.
replace_one(
    "evaluation/__init__.py",
    "from evaluation.decision_learning import (\n",
    "from evaluation.calibration import (\n    CalibrationDimension,\n    CalibrationMetric,\n    DecisionCalibrationSuite,\n    DecisionCalibrationSuiteBuilder,\n)\nfrom evaluation.decision_learning import (\n",
)
replace_one(
    "evaluation/__init__.py",
    "    \"CalibrationBucket\",\n",
    "    \"CalibrationBucket\",\n    \"CalibrationDimension\",\n    \"CalibrationMetric\",\n",
)
replace_one(
    "evaluation/__init__.py",
    "    \"DecisionEvidenceSnapshot\",\n",
    "    \"DecisionCalibrationSuite\",\n    \"DecisionCalibrationSuiteBuilder\",\n    \"DecisionEvidenceSnapshot\",\n",
)
replace_one(
    "cio/__init__.py",
    "    \"DecisionPolicyProfile\": (\"cio.policy_matrix\", \"DecisionPolicyProfile\"),\n",
    "    \"DecisionPolicyProfile\": (\"cio.policy_matrix\", \"DecisionPolicyProfile\"),\n    \"ChampionChallengerRegistry\": (\"cio.policy_governance\", \"ChampionChallengerRegistry\"),\n    \"PolicyPerformanceEvidence\": (\"cio.policy_governance\", \"PolicyPerformanceEvidence\"),\n    \"PolicyPromotionDecision\": (\"cio.policy_governance\", \"PolicyPromotionDecision\"),\n    \"PolicyPromotionPolicy\": (\"cio.policy_governance\", \"PolicyPromotionPolicy\"),\n    \"PolicyVersionCandidate\": (\"cio.policy_governance\", \"PolicyVersionCandidate\"),\n    \"PolicyVersionStatus\": (\"cio.policy_governance\", \"PolicyVersionStatus\"),\n",
)
replace_one(
    "cio/__init__.py",
    "    \"CIOAction\",\n",
    "    \"CIOAction\",\n    \"ChampionChallengerRegistry\",\n",
)
replace_one(
    "cio/__init__.py",
    "    \"PayoffDistributionPoint\",\n",
    "    \"PayoffDistributionPoint\",\n    \"PolicyPerformanceEvidence\",\n    \"PolicyPromotionDecision\",\n    \"PolicyPromotionPolicy\",\n    \"PolicyVersionCandidate\",\n    \"PolicyVersionStatus\",\n",
)
replace_one(
    "portfolio/construction_models.py",
    "    \"ConstructionIntent\",\n    \"ConstructionStatus\",\n",
    "    \"ConstructionIntent\",\n    \"ConstructionMode\",\n    \"ConstructionStatus\",\n",
)
replace_one(
    "portfolio/construction_api.py",
    "from portfolio.construction_engine import PortfolioConstructionEngine\n",
    "from portfolio.construction_engine import PortfolioConstructionEngine\nfrom portfolio.derivative_lifecycle import (\n    DerivativeLifecycleAssessment,\n    DerivativeLifecycleAuthority,\n    DerivativeLifecyclePolicy,\n    DerivativeLifecycleProfile,\n)\nfrom portfolio.scenario_authority import (\n    GovernedPortfolioScenario,\n    GovernedPortfolioScenarioSet,\n    PortfolioScenarioAuthority,\n)\n",
)
replace_one(
    "portfolio/construction_api.py",
    "    \"ExposureLimit\",\n",
    "    \"DerivativeLifecycleAssessment\",\n    \"DerivativeLifecycleAuthority\",\n    \"DerivativeLifecyclePolicy\",\n    \"DerivativeLifecycleProfile\",\n    \"ExposureLimit\",\n    \"GovernedPortfolioScenario\",\n    \"GovernedPortfolioScenarioSet\",\n",
)
replace_one(
    "portfolio/construction_api.py",
    "    \"PortfolioScenarioMetrics\",\n",
    "    \"PortfolioScenarioAuthority\",\n    \"PortfolioScenarioMetrics\",\n",
)

# README alignment with the six-specialist architecture and current portfolio engine.
replace_one(
    "README.md",
    "| Decision authority | Five independent specialists plus one Chief Investment Officer |",
    "| Decision authority | Six independent specialists plus one Chief Investment Officer |",
)
replace_one(
    "README.md",
    "Five independent specialist analyses",
    "Six independent specialist analyses",
)
replace_one(
    "README.md",
    "1. Macro & Economic Strategist\n2. Market Strategist\n3. Fundamental & Valuation Analyst\n4. Portfolio & Risk Manager\n5. Evidence & Governance Officer\n6. Chief Investment Officer\n\nThe first five complete independent first-pass analysis against the same evidence boundary.",
    "1. Macro & Economic Strategist\n2. Market Strategist\n3. Cross-Asset Forecast & Scenario Specialist\n4. Fundamental & Valuation Analyst\n5. Portfolio & Risk Manager\n6. Evidence & Governance Officer\n7. Chief Investment Officer\n\nThe first six complete independent first-pass analysis against the same evidence boundary.",
)
replace_one(
    "README.md",
    "- allocates positive intents in opportunity-rank order;",
    "- evaluates deterministic complete-portfolio candidates through beam search rather than accepting one greedy order;",
)
replace_one(
    "README.md",
    "- enforces position, sector, factor, correlation, liquidity, cash, turnover, cost, and currency constraints; and",
    "- applies one governed common-scenario set across every noncash holding and enforces position, sector, factor, correlation, liquidity, cash, turnover, cost, derivative-lifecycle, and currency constraints; and",
)
replace_one(
    "README.md",
    "Forecasts are supporting evidence, not an independent decision authority.",
    "Forecast records are supporting evidence, not independent action authority. The Cross-Asset Forecast & Scenario Specialist independently evaluates governed distributions, calibration, path risk, and cross-asset transmission, but only the CIO may issue an investment action.",
)
