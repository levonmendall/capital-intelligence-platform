from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "portfolio/construction_api.py",
        """from portfolio.construction_engine import PortfolioConstructionEngine
""",
        """from portfolio.construction_engine import PortfolioConstructionEngine
from portfolio.decision_reconciliation import (
    ConstructionDecisionReconciliation,
    ConstructionDisposition,
    reconcile_construction_decisions,
)
""",
    )
    replace_once(
        "portfolio/construction_api.py",
        """    \"ConstructionIntent\",
""",
        """    \"ConstructionDecisionReconciliation\",
    \"ConstructionDisposition\",
    \"ConstructionIntent\",
""",
    )
    replace_once(
        "portfolio/construction_api.py",
        """    \"TradeSide\",
]
""",
        """    \"TradeSide\",
    \"reconcile_construction_decisions\",
]
""",
    )

    replace_once(
        "cio/persistence.py",
        """    PORTFOLIO_CONSTRUCTION = \"portfolio_construction\"
    DECISION_EVIDENCE_SNAPSHOT = \"decision_evidence_snapshot\"
""",
        """    PORTFOLIO_CONSTRUCTION = \"portfolio_construction\"
    CONSTRUCTION_RECONCILIATION = \"construction_reconciliation\"
    DECISION_EVIDENCE_SNAPSHOT = \"decision_evidence_snapshot\"
""",
    )

    replace_once(
        "application/cio_cycle.py",
        """    ConstructionIntent,
    ConstructionMode,
""",
        """    ConstructionDecisionReconciliation,
    ConstructionIntent,
    ConstructionMode,
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """    TradeSide,
)
""",
        """    TradeSide,
    reconcile_construction_decisions,
)
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """    construction: PortfolioConstructionResult | None
    theses: tuple[LivingThesis, ...]
""",
        """    construction: PortfolioConstructionResult | None
    construction_reconciliations: tuple[
        ConstructionDecisionReconciliation, ...
    ]
    theses: tuple[LivingThesis, ...]
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        if not isinstance(self.theses, tuple) or not all(
            isinstance(item, LivingThesis) for item in self.theses
        ):
""",
        """        if not isinstance(self.construction_reconciliations, tuple) or not all(
            isinstance(item, ConstructionDecisionReconciliation)
            for item in self.construction_reconciliations
        ):
            raise TypeError(
                \"construction_reconciliations must contain \"
                \"ConstructionDecisionReconciliation values\"
            )
        if len(self.construction_reconciliations) != len(self.decisions):
            raise ValueError(
                \"each CIO decision must have one construction reconciliation\"
            )
        if not isinstance(self.theses, tuple) or not all(
            isinstance(item, LivingThesis) for item in self.theses
        ):
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """        if self.journal is not None and construction is not None:
            append_construction(
                self.journal,
                construction,
                code_version=code_version or \"unknown\",
            )
        theses = self._create_theses(
""",
        """        if self.journal is not None and construction is not None:
            append_construction(
                self.journal,
                construction,
                code_version=code_version or \"unknown\",
            )
        construction_reconciliations = reconcile_construction_decisions(
            decisions=tuple(decisions),
            candidates=tuple(
                ranked_by_candidate[item.candidate_identifier].candidate
                for item in decisions
            ),
            construction=construction,
        )
        if self.journal is not None:
            for item in construction_reconciliations:
                self.journal.append(
                    event_type=(
                        CIOJournalEventType.CONSTRUCTION_RECONCILIATION
                    ),
                    aggregate_identifier=item.candidate_identifier,
                    occurred_at=portfolio.as_of,
                    payload={
                        **item.to_dict(),
                        \"cycle_identifier\": cycle_identifier,
                        \"code_version\": code_version or \"unknown\",
                    },
                    schema_version=\"construction-reconciliation.v1\",
                    event_identifier=(
                        f\"event:construction-reconciliation:{item.decision_identifier}\"
                    ),
                )
        theses = self._create_theses(
""",
    )
    replace_once(
        "application/cio_cycle.py",
        """            construction=construction,
            theses=theses,
""",
        """            construction=construction,
            construction_reconciliations=construction_reconciliations,
            theses=theses,
""",
    )

    replace_once(
        "tests/test_canonical_cio_cycle.py",
        """    assert journal.count() == 8
""",
        """    assert journal.count() == 9
""",
    )


if __name__ == "__main__":
    main()
