from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "paper-evidence-path-summary.md"
TERMS = (
    "CandidateDecisionRecord",
    "ProductionCandidateEvidence",
    "ProductionHoldingEvidence",
    "AssetSpecificEvidencePacket",
    "CandidateForecastSupport",
    "TechnicalMomentum",
    "Valuation",
    "LivingThesis",
    "HistoricalLearning",
    "PriceBar",
    "MarketDataProvider",
    "AnalyticalEngineResult",
)
PREFIXES = (
    "application/",
    "cio/",
    "committee/",
    "company/",
    "data/",
    "evaluation/",
    "forecasting/",
    "governance/",
    "historical_replay/",
    "intelligence/",
    "market/",
    "operations/",
    "portfolio/",
    "providers/",
    "screening/",
    "thesis/",
)


def defs(source: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], []
    classes: list[str] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
    return classes, functions


def main() -> None:
    lines = ["# Paper Evidence Path Summary", ""]
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if ".git" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        matches = [term for term in TERMS if term.lower() in source.lower()]
        if not matches and not relative.startswith(PREFIXES):
            continue
        classes, functions = defs(source)
        if not matches and not classes and not functions:
            continue
        lines.extend(
            [
                f"## `{relative}`",
                f"- Terms: {', '.join(matches) if matches else 'package inventory'}",
                f"- Classes: {', '.join(classes) if classes else 'none'}",
                f"- Functions: {', '.join(functions) if functions else 'none'}",
                "",
            ]
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
