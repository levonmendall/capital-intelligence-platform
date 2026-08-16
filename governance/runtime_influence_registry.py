"""Machine-enforced whole-system connectivity and influence registry.

The registry answers two different questions that were previously easy to conflate:

1. Is a production-capable module reachable from an actual runtime entrypoint?
2. If a capability is intended to matter to a governed decision, is there an explicit
   producer -> consumer -> influence contract proving where it is allowed to matter?

The audit is deliberately static and deterministic. It does not grant investment
or execution authority. It is an architectural control used by CI to prevent
implemented features from silently becoming orphaned, accidentally authoritative,
or misleadingly described as connected.
"""

from __future__ import annotations

import ast
import json
from collections import Counter, deque
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping


class ComponentLifecycle(str, Enum):
    AUTHORITATIVE = "authoritative"
    DECISION_INPUT = "decision_input"
    GOVERNED_ADVISORY = "governed_advisory"
    LEARNING_CALIBRATION = "learning_calibration"
    SHADOW = "shadow"
    PRESENTATION_ONLY = "presentation_only"
    OPERATIONAL = "operational"
    EXPERIMENTAL = "experimental"
    SUPERSEDED = "superseded"
    ORPHANED = "orphaned"


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    """Declared lifecycle and intended influence path for one named capability."""

    name: str
    lifecycle: ComponentLifecycle
    producers: tuple[str, ...]
    consumers: tuple[str, ...] = ()
    runtime_entrypoints: tuple[str, ...] = ()
    influence_targets: tuple[str, ...] = ()
    feedback_path: tuple[str, ...] = ()
    counterfactual_tests: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    require_import_path: bool = True

    @property
    def requires_influence(self) -> bool:
        return self.lifecycle in {
            ComponentLifecycle.AUTHORITATIVE,
            ComponentLifecycle.DECISION_INPUT,
            ComponentLifecycle.GOVERNED_ADVISORY,
            ComponentLifecycle.LEARNING_CALIBRATION,
        }


# Capabilities that have outsized product meaning are declared explicitly instead of
# being inferred from directory names. Shadow/presentation declarations are equally
# important: they prevent a sophisticated downstream sidecar from being mistaken for
# investment authority merely because it exists and runs.
CAPABILITY_CONTRACTS: tuple[CapabilityContract, ...] = (
    CapabilityContract(
        name="canonical_cio_decision_chain",
        lifecycle=ComponentLifecycle.AUTHORITATIVE,
        producers=("application.cio_cycle",),
        consumers=(
            "application.production_context_contract",
            "application.production_context_executor",
        ),
        runtime_entrypoints=("run_scheduler", "run_autonomous_paper_operator"),
        influence_targets=(
            "specialist_packet",
            "cio_decision",
            "portfolio_construction",
            "living_thesis",
        ),
        notes=(
            "CIO remains the sole investment authority; existing CIO-cycle behavior is covered by the canonical executor and production-context test suites.",
        ),
    ),
    CapabilityContract(
        name="forward_intelligence",
        lifecycle=ComponentLifecycle.DECISION_INPUT,
        producers=("intelligence.forward",),
        consumers=("committee.specialists", "application.cio_cycle"),
        runtime_entrypoints=("run_scheduler", "run_autonomous_paper_operator"),
        influence_targets=(
            "specialist.expected_return_impact",
            "specialist.confidence",
            "specialist.scenario_adjustments",
            "specialist.evidence_lineage",
        ),
        counterfactual_tests=("tests/test_forward_intelligence.py",),
        notes=(
            "Forward intelligence enriches the existing specialists and cannot authorize capital.",
        ),
    ),
    CapabilityContract(
        name="active_investor_expression_and_lifecycle",
        lifecycle=ComponentLifecycle.GOVERNED_ADVISORY,
        producers=("portfolio.active_investor",),
        consumers=("application.compounding_cycle",),
        runtime_entrypoints=("run_scheduler", "run_autonomous_paper_operator"),
        influence_targets=(
            "investment_view",
            "expression_ranking",
            "position_lifecycle_plan",
            "reactive_monitoring_plan",
        ),
        notes=(
            "Active-investor outputs are advisory/monitoring contracts and have no trade authority.",
        ),
    ),
    CapabilityContract(
        name="reactive_monitoring_plan",
        lifecycle=ComponentLifecycle.GOVERNED_ADVISORY,
        producers=("portfolio.active_investor",),
        consumers=(
            "operations.reactive_monitoring_runtime",
            "operations.reactive_investor_material_reassessment",
        ),
        runtime_entrypoints=("run_autonomous_paper_operator",),
        influence_targets=("canonical_cio_reassessment_request",),
        counterfactual_tests=("tests/test_reactive_monitoring_runtime.py",),
        notes=(
            "The hash-chain-verified plan can now request a canonical CIO reassessment when qualified evidence matches a declared dependency; it has no portfolio or execution authority.",
        ),
    ),
    CapabilityContract(
        name="investor_material_reassessment",
        lifecycle=ComponentLifecycle.OPERATIONAL,
        producers=("operations.investor_material_reassessment",),
        consumers=("operations.cio_reassessment", "run_autonomous_paper_operator"),
        runtime_entrypoints=("run_autonomous_paper_operator",),
        influence_targets=("canonical_cio_reassessment_request",),
        notes=("Monitoring may request reassessment but cannot authorize a portfolio change.",),
    ),
    CapabilityContract(
        name="causal_intelligence_sidecar",
        lifecycle=ComponentLifecycle.SHADOW,
        producers=("evaluation.causal_intelligence_runtime",),
        require_import_path=False,
        notes=(
            "Causal intelligence is intentionally downstream/shadow until explicitly promoted through governed validation.",
        ),
    ),
    CapabilityContract(
        name="forecast_calibration",
        lifecycle=ComponentLifecycle.SHADOW,
        producers=("evaluation.forecast_calibration",),
        require_import_path=False,
        notes=(
            "Calibration may measure confidence quality, but no policy change is authorized until an explicit governed feedback consumer exists.",
        ),
    ),
    CapabilityContract(
        name="decision_intelligence_v3",
        lifecycle=ComponentLifecycle.PRESENTATION_ONLY,
        producers=("application.decision_intelligence_v3_runtime",),
        consumers=("intelligence.ask_cio",),
        runtime_entrypoints=("run_scheduler", "run_autonomous_paper_operator"),
        notes=(
            "Decision Intelligence v3 writes a durable store consumed by Ask CIO; it is downstream explainability/measurement, not CIO authority.",
        ),
        require_import_path=False,
    ),
    CapabilityContract(
        name="universal_capability_graph",
        lifecycle=ComponentLifecycle.SHADOW,
        producers=("operations.universal_capability_graph",),
        require_import_path=False,
        notes=(
            "The graph is implemented and validated but remains shadow until the production eligibility boundary consumes it authoritatively.",
        ),
    ),
    CapabilityContract(
        name="automatic_instrument_eligibility_factory",
        lifecycle=ComponentLifecycle.SHADOW,
        producers=("operations.instrument_eligibility_factory",),
        require_import_path=False,
        notes=(
            "Automatic promotion remains shadow until its reconcile path is called by a production evidence owner.",
        ),
    ),
    CapabilityContract(
        name="universal_paper_contract",
        lifecycle=ComponentLifecycle.SHADOW,
        producers=("operations.universal_paper_contract",),
        require_import_path=False,
        notes=(
            "Normalized universal paper intents remain shadow while the legacy multi-asset execution contract is authoritative.",
        ),
    ),
    CapabilityContract(
        name="canonical_paper_execution",
        lifecycle=ComponentLifecycle.AUTHORITATIVE,
        producers=("paper_execution_runtime", "run_approved_paper_execution"),
        consumers=("run_autonomous_paper_operator",),
        runtime_entrypoints=("run_autonomous_paper_operator",),
        influence_targets=("paper_order", "paper_fill", "reconciliation"),
        notes=("Paper only; real-money authorization remains false.",),
    ),
    CapabilityContract(
        name="serving_readiness",
        lifecycle=ComponentLifecycle.OPERATIONAL,
        producers=("operations.readiness",),
        runtime_entrypoints=("run_render_service",),
        influence_targets=("service_restart_boundary",),
        notes=(
            "Serving readiness is intentionally separate from fail-closed evidence/decision/execution readiness.",
        ),
        require_import_path=False,
    ),
)


_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "reports",
        "artifacts",
        "build",
        "dist",
        "node_modules",
    }
)

_RUNTIME_ROOT_NAMES = frozenset(
    {
        "app",
        "render_app",
        "initialize",
        "capital_intelligence_cli",
        "api.app",
    }
)


@dataclass(frozen=True, slots=True)
class ModuleRecord:
    module: str
    path: str
    lifecycle: ComponentLifecycle
    reachable: bool
    runtime_roots: tuple[str, ...]
    imports: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilityAudit:
    name: str
    lifecycle: ComponentLifecycle
    valid: bool
    issues: tuple[str, ...]
    producers: tuple[str, ...]
    consumers: tuple[str, ...]
    runtime_entrypoints: tuple[str, ...]
    influence_targets: tuple[str, ...]
    feedback_path: tuple[str, ...]
    counterfactual_tests: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeInfluenceAudit:
    schema_version: str
    module_count: int
    reachable_module_count: int
    unreachable_module_count: int
    lifecycle_counts: Mapping[str, int]
    runtime_roots: tuple[str, ...]
    modules: tuple[ModuleRecord, ...]
    capabilities: tuple[CapabilityAudit, ...]
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "module_count": self.module_count,
            "reachable_module_count": self.reachable_module_count,
            "unreachable_module_count": self.unreachable_module_count,
            "lifecycle_counts": dict(self.lifecycle_counts),
            "runtime_roots": list(self.runtime_roots),
            "modules": [
                {
                    **asdict(item),
                    "lifecycle": item.lifecycle.value,
                    "runtime_roots": list(item.runtime_roots),
                    "imports": list(item.imports),
                }
                for item in self.modules
            ],
            "capabilities": [
                {
                    **asdict(item),
                    "lifecycle": item.lifecycle.value,
                    "issues": list(item.issues),
                    "producers": list(item.producers),
                    "consumers": list(item.consumers),
                    "runtime_entrypoints": list(item.runtime_entrypoints),
                    "influence_targets": list(item.influence_targets),
                    "feedback_path": list(item.feedback_path),
                    "counterfactual_tests": list(item.counterfactual_tests),
                    "notes": list(item.notes),
                }
                for item in self.capabilities
            ],
            "violations": list(self.violations),
        }

    def write_json(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def discover_modules(root: str | Path) -> dict[str, Path]:
    base = Path(root).resolve()
    modules: dict[str, Path] = {}
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(base)
        if "tests" in relative.parts or any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        module = _module_name(base, path)
        if module:
            modules[module] = path
    return modules


def _package_for(module: str, path: Path) -> str:
    if path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _best_module(candidate: str, modules: Mapping[str, Path]) -> str | None:
    if candidate in modules:
        return candidate
    parts = candidate.split(".")
    while len(parts) > 1:
        parts.pop()
        possible = ".".join(parts)
        if possible in modules:
            return possible
    return None


def _imports_for(
    *,
    module: str,
    path: Path,
    modules: Mapping[str, Path],
) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    resolved: set[str] = set()
    package = _package_for(module, path)
    package_parts = package.split(".") if package else []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _best_module(alias.name, modules)
                if target is not None:
                    resolved.add(target)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                trim = max(0, node.level - 1)
                base_parts = package_parts[: len(package_parts) - trim]
                if node.module:
                    base_parts.extend(node.module.split("."))
                base = ".".join(part for part in base_parts if part)
            else:
                base = node.module or ""
            base_target = _best_module(base, modules) if base else None
            if base_target is not None:
                resolved.add(base_target)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}" if base else alias.name
                target = _best_module(candidate, modules)
                if target is not None:
                    resolved.add(target)
    resolved.discard(module)
    return resolved


def build_import_graph(
    root: str | Path,
    modules: Mapping[str, Path] | None = None,
) -> dict[str, set[str]]:
    base = Path(root).resolve()
    discovered = dict(modules or discover_modules(base))
    return {
        module: _imports_for(module=module, path=path, modules=discovered)
        for module, path in discovered.items()
    }


def runtime_roots(modules: Mapping[str, Path]) -> tuple[str, ...]:
    roots = {
        module
        for module in modules
        if module in _RUNTIME_ROOT_NAMES
        or ("." not in module and module.startswith("run_"))
    }
    return tuple(sorted(roots))


def _reachable(graph: Mapping[str, set[str]], roots: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    pending = deque(item for item in roots if item in graph)
    while pending:
        module = pending.popleft()
        if module in seen:
            continue
        seen.add(module)
        pending.extend(item for item in graph.get(module, ()) if item not in seen)
    return seen


def _roots_reaching(
    graph: Mapping[str, set[str]],
    roots: Iterable[str],
    target: str,
) -> tuple[str, ...]:
    return tuple(root for root in roots if target in _reachable(graph, (root,)))


def _has_import_path(
    graph: Mapping[str, set[str]],
    *,
    start: str,
    target: str,
) -> bool:
    return target in _reachable(graph, (start,))


def classify_module(module: str, path: Path, *, reachable: bool) -> ComponentLifecycle:
    lowered = str(path).lower()
    stem = path.stem.lower()
    if "legacy" in lowered:
        return ComponentLifecycle.SUPERSEDED
    if any(token in stem for token in ("preview", "preliminary", "fixture", "demo")):
        return ComponentLifecycle.EXPERIMENTAL
    if "." not in module and module.startswith("run_"):
        return ComponentLifecycle.OPERATIONAL
    if module in _RUNTIME_ROOT_NAMES:
        return ComponentLifecycle.OPERATIONAL
    prefix = module.split(".", 1)[0]
    if prefix in {"presentation", "reporting"}:
        lifecycle = ComponentLifecycle.PRESENTATION_ONLY
    elif prefix == "api":
        lifecycle = ComponentLifecycle.PRESENTATION_ONLY
    elif prefix == "evaluation":
        lifecycle = ComponentLifecycle.LEARNING_CALIBRATION
    elif prefix in {"intelligence", "committee", "opportunity", "screening"}:
        lifecycle = ComponentLifecycle.DECISION_INPUT
    elif prefix in {"application", "cio", "portfolio", "governance"}:
        lifecycle = ComponentLifecycle.AUTHORITATIVE
    elif prefix in {"operations", "scripts", "delivery"}:
        lifecycle = ComponentLifecycle.OPERATIONAL
    elif prefix in {"providers", "provider", "data", "information", "market_data", "public_information"}:
        lifecycle = ComponentLifecycle.DECISION_INPUT
    else:
        lifecycle = ComponentLifecycle.OPERATIONAL
    if not reachable and lifecycle in {
        ComponentLifecycle.AUTHORITATIVE,
        ComponentLifecycle.DECISION_INPUT,
        ComponentLifecycle.LEARNING_CALIBRATION,
    }:
        return ComponentLifecycle.ORPHANED
    return lifecycle


def _audit_capability(
    contract: CapabilityContract,
    *,
    root: Path,
    modules: Mapping[str, Path],
    graph: Mapping[str, set[str]],
    reachable: set[str],
) -> CapabilityAudit:
    issues: list[str] = []
    for producer in contract.producers:
        if producer not in modules:
            issues.append(f"producer module is missing: {producer}")
    for consumer in contract.consumers:
        if consumer not in modules:
            issues.append(f"consumer module is missing: {consumer}")
    for entrypoint in contract.runtime_entrypoints:
        if entrypoint not in modules:
            issues.append(f"runtime entrypoint is missing: {entrypoint}")
    if contract.lifecycle not in {
        ComponentLifecycle.SHADOW,
        ComponentLifecycle.EXPERIMENTAL,
        ComponentLifecycle.SUPERSEDED,
        ComponentLifecycle.PRESENTATION_ONLY,
    }:
        for producer in contract.producers:
            if producer in modules and producer not in reachable:
                issues.append(f"producer is not reachable from a runtime entrypoint: {producer}")
        for consumer in contract.consumers:
            if consumer in modules and consumer not in reachable:
                issues.append(f"consumer is not reachable from a runtime entrypoint: {consumer}")
    if contract.require_import_path and contract.consumers:
        for producer in contract.producers:
            if producer not in modules:
                continue
            if not any(
                consumer in modules
                and _has_import_path(graph, start=consumer, target=producer)
                for consumer in contract.consumers
            ):
                issues.append(f"no declared consumer has an import path to producer: {producer}")
    if contract.requires_influence and not contract.influence_targets:
        issues.append("governed capability has no declared influence target")
    if contract.lifecycle is ComponentLifecycle.LEARNING_CALIBRATION and not contract.feedback_path:
        issues.append("learning/calibration capability has no declared feedback path")
    for test_path in contract.counterfactual_tests:
        if not (root / test_path).is_file():
            issues.append(f"counterfactual test is missing: {test_path}")
    return CapabilityAudit(
        name=contract.name,
        lifecycle=contract.lifecycle,
        valid=not issues,
        issues=tuple(issues),
        producers=contract.producers,
        consumers=contract.consumers,
        runtime_entrypoints=contract.runtime_entrypoints,
        influence_targets=contract.influence_targets,
        feedback_path=contract.feedback_path,
        counterfactual_tests=contract.counterfactual_tests,
        notes=contract.notes,
    )


def audit_repository(root: str | Path) -> RuntimeInfluenceAudit:
    base = Path(root).resolve()
    modules = discover_modules(base)
    graph = build_import_graph(base, modules)
    roots = runtime_roots(modules)
    reachable = _reachable(graph, roots)
    records = tuple(
        ModuleRecord(
            module=module,
            path=str(path.relative_to(base)),
            lifecycle=classify_module(module, path, reachable=module in reachable),
            reachable=module in reachable,
            runtime_roots=_roots_reaching(graph, roots, module),
            imports=tuple(sorted(graph.get(module, ()))),
        )
        for module, path in sorted(modules.items())
    )
    capabilities = tuple(
        _audit_capability(
            contract,
            root=base,
            modules=modules,
            graph=graph,
            reachable=reachable,
        )
        for contract in CAPABILITY_CONTRACTS
    )
    violations = tuple(
        f"{item.name}: {issue}"
        for item in capabilities
        for issue in item.issues
    )
    counts = Counter(item.lifecycle.value for item in records)
    return RuntimeInfluenceAudit(
        schema_version="runtime-influence-audit.v1",
        module_count=len(records),
        reachable_module_count=sum(1 for item in records if item.reachable),
        unreachable_module_count=sum(1 for item in records if not item.reachable),
        lifecycle_counts=dict(sorted(counts.items())),
        runtime_roots=roots,
        modules=records,
        capabilities=capabilities,
        violations=violations,
    )


__all__ = [
    "CAPABILITY_CONTRACTS",
    "CapabilityAudit",
    "CapabilityContract",
    "ComponentLifecycle",
    "ModuleRecord",
    "RuntimeInfluenceAudit",
    "audit_repository",
    "build_import_graph",
    "classify_module",
    "discover_modules",
    "runtime_roots",
]
