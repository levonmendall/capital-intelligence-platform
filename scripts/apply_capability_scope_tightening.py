"""Keep exact capability authority limited to the fixed bounded pilot."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing patch anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "production_context_publication_governed.py",
        "capability_authority = BoundedPilotCapabilityAuthority.from_universe(universe)",
        "capability_authority = BoundedPilotCapabilityAuthority.from_universe(base_universe)",
    )
    replace_once(
        "application/production_context_contract.py",
        "from opportunity import OpportunityEngine\nfrom screening import candidate_from_payload\n",
        "from opportunity import OpportunityEngine\n"
        "from operations.free_paper_pilot import load_free_paper_pilot_universe\n"
        "from screening import candidate_from_payload\n",
    )
    replace_once(
        "application/production_context_contract.py",
        '''            capability_authority = BoundedPilotCapabilityAuthority.from_candidates(\n                candidates,\n                authority_identifier=publication.universe_snapshot_identifier,\n            )\n''',
        '''            capability_authority = BoundedPilotCapabilityAuthority.from_universe(\n                load_free_paper_pilot_universe()\n            )\n''',
    )
    report = Path("UNIVERSE_CAPABILITY_REMEDIATION.md")
    text = report.read_text(encoding="utf-8")
    text = text.replace(
        "   - Production publication injects the exact bounded-pilot authority into the queue used by the canonical CIO cycle.\n",
        "   - Production publication injects authority derived only from the fixed 15-instrument base pilot, not the post-discovery universe.\n",
    )
    text = text.replace(
        "   - The production executor reconstructs an equivalent exact authority from the persisted complete-universe publication before independently reconciling and running the queue.\n",
        "   - The production executor independently reloads the same fixed base-pilot authority before reconciling and running the queue.\n",
    )
    report.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
