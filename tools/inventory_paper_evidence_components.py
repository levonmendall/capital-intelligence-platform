from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "paper-evidence-component-inventory.json"

TERMS = (
    "CandidateDecisionRecord",
    "ProductionCandidateEvidence",
    "ProductionHoldingEvidence",
    "ProductionContextEvidenceSnapshot",
    "CandidateForecastSupport",
    "ForecastScenario",
    "historical_learning",
    "technical",
    "momentum",
    "valuation",
    "LivingThesis",
    "latest_quotes",
    "bars",
    "get_observations",
    "public_live",
    "originating_fact",
    "evidence_identifiers",
)

INTERESTING_ROOTS = {
    "application",
    "cio",
    "committee",
    "company",
    "data",
    "evaluation",
    "forecasting",
    "governance",
    "historical_replay",
    "market",
    "opportunity",
    "operations",
    "portfolio",
    "providers",
    "screening",
    "thesis",
}


def definitions(source: str) -> dict[str, list[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"classes": [], "functions": []}
    classes: list[str] = []
    functions: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
    return {
        "classes": sorted(set(classes)),
        "functions": sorted(set(functions)),
    }


def excerpts(lines: list[str], line_numbers: set[int]) -> list[dict[str, object]]:
    groups: list[tuple[int, int]] = []
    for line_number in sorted(line_numbers):
        start = max(1, line_number - 3)
        end = min(len(lines), line_number + 5)
        if groups and start <= groups[-1][1] + 1:
            groups[-1] = (groups[-1][0], max(groups[-1][1], end))
        else:
            groups.append((start, end))
    result: list[dict[str, object]] = []
    for start, end in groups[:12]:
        result.append(
            {
                "start_line": start,
                "end_line": end,
                "text": "\n".join(
                    f"{index}: {lines[index - 1]}" for index in range(start, end + 1)
                ),
            }
        )
    return result


def main() -> None:
    files: list[dict[str, object]] = []
    all_paths: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        relative_text = relative.as_posix()
        all_paths.append(relative_text)
        if path.suffix != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = source.splitlines()
        matched: dict[str, list[int]] = {}
        for term in TERMS:
            hits = [
                index
                for index, line in enumerate(lines, start=1)
                if term.lower() in line.lower()
            ]
            if hits:
                matched[term] = hits
        root = relative.parts[0] if relative.parts else ""
        if not matched and root not in INTERESTING_ROOTS:
            continue
        relevant_lines = {line for hits in matched.values() for line in hits}
        files.append(
            {
                "path": relative_text,
                "line_count": len(lines),
                "definitions": definitions(source),
                "matches": matched,
                "excerpts": excerpts(lines, relevant_lines),
            }
        )

    payload = {
        "schema_version": "paper-evidence-component-inventory.v1",
        "file_count": len(all_paths),
        "python_component_count": len(files),
        "paths": all_paths,
        "components": files,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
