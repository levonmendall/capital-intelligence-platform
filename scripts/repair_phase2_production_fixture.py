from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, found {count}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "tests/test_canonical_production_context_adapter.py"
    replace_once(
        path,
        """from committee.specialists import (
    MacroSpecialistContext,
    MarketSpecialistContext,
)
""",
        """from committee.specialists import (
    AssetValuationSpecialistContext,
    MacroSpecialistContext,
    MarketSpecialistContext,
)
""",
    )
    replace_once(
        path,
        """        company=None,
        exposure_profile=CandidateExposureProfile(
""",
        """        company=None,
        asset_valuation=AssetValuationSpecialistContext(
            as_of=AS_OF,
            asset_class=candidate.instrument.asset_class,
            expected_return_impact=0.02,
            confidence=0.90,
            valuation_evidence=(
                "Point-in-time ETF holdings, earnings, valuation, and return-driver evidence is complete",
            ),
            contradictory_evidence=(
                "Underlying valuation relationships may change before implementation",
            ),
            critical_assumptions=(
                "The fund continues to represent its disclosed broad-market exposure",
            ),
            risks=(
                "Tracking, composition, and valuation relationships can change",
            ),
            limitations=(
                "The asset-specific valuation packet is point-in-time",
            ),
            change_conditions=(
                "Reassess after a material holdings, valuation, or methodology change",
            ),
            evidence_identifiers=(
                "evidence:asset-valuation:spy",
            ),
        ),
        exposure_profile=CandidateExposureProfile(
""",
    )
    replace_once(
        path,
        """            "evidence:fundamental:spy",
        ),
""",
        """            "evidence:fundamental:spy",
            "evidence:asset-valuation:spy",
        ),
""",
    )


if __name__ == "__main__":
    main()
