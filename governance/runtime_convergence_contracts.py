"""High-meaning influence contracts added during whole-system convergence.

These contracts supplement the baseline runtime registry with proof for the two live
paths that most directly answer whether the platform's forward-looking and learning
capabilities actually affect the governed CIO process.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from governance.runtime_influence_registry import (
    ComponentLifecycle,
    build_import_graph,
    discover_modules,
    runtime_roots,
)


@dataclass(frozen=True, slots=True)
class RuntimeConvergenceContract:
    name: str
    lifecycle: ComponentLifecycle
    producer: str
    consumers: tuple[str, ...]
    entrypoints: tuple[str, ...]
    influence_targets: tuple[str, ...]
    counterfactual_tests: tuple[str, ...]
    feedback_path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.producer.strip():
            raise ValueError("convergence contract name and producer are required")
        if not self.consumers or not self.entrypoints or not self.influence_targets:
            raise ValueError("live convergence contracts require consumers, entrypoints, and influence targets")
        if self.lifecycle is ComponentLifecycle.LEARNING_CALIBRATION and not self.feedback_path:
            raise ValueError("learning/calibration convergence requires a feedback path")


CONVERGENCE_CONTRACTS: tuple[RuntimeConvergenceContract, ...] = (
    RuntimeConvergenceContract(
        name="global_rotation_production_cycle",
        lifecycle=ComponentLifecycle.AUTHORITATIVE,
        producer="application.global_rotation_cycle",
        consumers=("application.compounding_executor",),
        entrypoints=("run_scheduler", "run_autonomous_paper_operator"),
        influence_targets=(
            "authoritative_opportunity_rotation",
            "six_specialist_preliminary_conviction",
            "joint_marginal_capital_targets",
            "canonical_cio_decision",
        ),
        counterfactual_tests=(
            "tests/test_compounding_executor_cycle_binding.py",
            "tests/test_global_rotation_production_binding.py",
            "tests/test_global_rotation_preview.py",
        ),
    ),
    RuntimeConvergenceContract(
        name="governed_historical_learning_feedback",
        lifecycle=ComponentLifecycle.LEARNING_CALIBRATION,
        producer="cio.governed_historical_learning",
        consumers=("application.cio_cycle", "committee.specialists"),
        entrypoints=("run_scheduler", "run_autonomous_paper_operator"),
        influence_targets=(
            "specialist_confidence_ceiling",
            "specialist_evidence_lineage",
            "position_size_multiplier",
            "canonical_cio_synthesis",
        ),
        feedback_path=(
            "matured_point_in_time_outcomes",
            "canonical_historical_learning_manifest",
            "HistoricalLearningResolver",
            "CandidateSpecialistContext",
            "IndependentSpecialistService._historically_calibrate",
            "canonical_cio_synthesis",
        ),
        counterfactual_tests=(
            "tests/test_governed_historical_learning.py",
            "tests/test_horizon_aligned_historical_learning.py",
            "tests/test_cio_intelligence_refinement.py",
        ),
    ),
)


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    pending = deque((start,))
    while pending:
        module = pending.popleft()
        if module in seen or module not in graph:
            continue
        seen.add(module)
        pending.extend(item for item in graph[module] if item not in seen)
    return seen


def validate_convergence_contracts(root: str | Path) -> tuple[str, ...]:
    base = Path(root).resolve()
    modules = discover_modules(base)
    graph = build_import_graph(base, modules)
    roots = set(runtime_roots(modules))
    issues: list[str] = []
    for contract in CONVERGENCE_CONTRACTS:
        if contract.producer not in modules:
            issues.append(f"{contract.name}: missing producer {contract.producer}")
            continue
        producer_runtime_roots = tuple(
            entrypoint
            for entrypoint in contract.entrypoints
            if entrypoint in roots and contract.producer in _reachable(graph, entrypoint)
        )
        missing_entrypoints = tuple(
            item for item in contract.entrypoints if item not in modules
        )
        issues.extend(
            f"{contract.name}: missing runtime entrypoint {item}"
            for item in missing_entrypoints
        )
        if not producer_runtime_roots:
            issues.append(
                f"{contract.name}: producer is not reachable from any declared runtime entrypoint"
            )
        for consumer in contract.consumers:
            if consumer not in modules:
                issues.append(f"{contract.name}: missing consumer {consumer}")
                continue
            if contract.producer not in _reachable(graph, consumer):
                issues.append(
                    f"{contract.name}: consumer {consumer} has no import path to producer {contract.producer}"
                )
        for test_path in contract.counterfactual_tests:
            if not (base / test_path).is_file():
                issues.append(f"{contract.name}: missing counterfactual test {test_path}")
    return tuple(issues)


__all__ = [
    "CONVERGENCE_CONTRACTS",
    "RuntimeConvergenceContract",
    "validate_convergence_contracts",
]
