"""Point-in-time primary-source document interpretation and comparison.

The engine compares exact passages and records factual versus interpretive conclusions.
It does not authorize capital, create candidates, or convert tone into a trade signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from typing import Any


class DocumentKind(str, Enum):
    SEC_FILING = "sec_filing"
    EARNINGS_RELEASE = "earnings_release"
    INVESTOR_PRESENTATION = "investor_presentation"
    TRANSCRIPT = "transcript"
    GUIDANCE = "guidance"
    CENTRAL_BANK = "central_bank"
    REGULATORY = "regulatory"
    MERGER = "merger"
    CREDIT_AGREEMENT = "credit_agreement"
    CORPORATE_ANNOUNCEMENT = "corporate_announcement"


class ConclusionType(str, Enum):
    FACT = "fact"
    INTERPRETATION = "interpretation"


@dataclass(frozen=True, slots=True)
class PrimarySourceDocument:
    identifier: str
    kind: DocumentKind
    issuer_identifier: str
    published_at: datetime
    available_at: datetime
    sections: tuple[tuple[str, str], ...]
    source_uri: str

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.issuer_identifier.strip():
            raise ValueError("document identifiers are required")
        if self.published_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("document timestamps must be timezone-aware")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        if not self.sections or any(not name.strip() or not text.strip() for name, text in self.sections):
            raise ValueError("sections must contain named, non-empty passages")

    def section_map(self) -> dict[str, str]:
        return dict(self.sections)


@dataclass(frozen=True, slots=True)
class DocumentConclusion:
    identifier: str
    section: str
    prior_passage: str | None
    current_passage: str
    semantic_change: str
    investment_significance: str
    confidence: float
    conclusion_type: ConclusionType
    exposures_affected: tuple[str, ...]
    numerical_claims: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "section": self.section,
            "prior_passage": self.prior_passage,
            "current_passage": self.current_passage,
            "semantic_change": self.semantic_change,
            "investment_significance": self.investment_significance,
            "confidence": self.confidence,
            "conclusion_type": self.conclusion_type.value,
            "exposures_affected": list(self.exposures_affected),
            "numerical_claims": list(self.numerical_claims),
            "authorizes_portfolio_change": False,
        }


@dataclass(frozen=True, slots=True)
class DocumentChangeAnalysis:
    current_document_identifier: str
    prior_document_identifier: str | None
    conclusions: tuple[DocumentConclusion, ...]
    missing_document_disclosure: str | None = None


class PrimarySourceDocumentEngine:
    version = "primary-source-documents.v1"
    _numbers = re.compile(r"(?<!\w)(?:\$|€|£)?-?\d+(?:\.\d+)?%?(?!\w)")
    _risk_terms = ("risk", "uncertain", "material weakness", "covenant", "liquidity")
    _guidance_terms = ("guidance", "outlook", "expects", "forecast", "target")
    _capital_terms = ("buyback", "dividend", "capex", "debt", "acquisition")

    def analyze(
        self,
        current: PrimarySourceDocument,
        *,
        prior: PrimarySourceDocument | None = None,
        exposures: tuple[str, ...] = (),
    ) -> DocumentChangeAnalysis:
        if prior is not None:
            if prior.issuer_identifier != current.issuer_identifier:
                raise ValueError("documents must belong to the same issuer")
            if prior.available_at >= current.available_at:
                raise ValueError("document comparison must be time ordered")
        prior_sections = prior.section_map() if prior else {}
        conclusions: list[DocumentConclusion] = []
        for section, current_passage in current.sections:
            prior_passage = prior_sections.get(section)
            similarity = SequenceMatcher(None, prior_passage or "", current_passage).ratio()
            if prior_passage == current_passage:
                continue
            lowered = current_passage.lower()
            prior_lowered = (prior_passage or "").lower()
            numbers = tuple(self._numbers.findall(current_passage))
            category = "new or changed narrative"
            significance = "Requires specialist interpretation; no independent capital effect."
            confidence = 0.55
            conclusion_type = ConclusionType.INTERPRETATION
            if numbers and numbers != tuple(self._numbers.findall(prior_passage or "")):
                category = "numerical disclosure changed"
                significance = "Reconcile the changed number to structured filing evidence before use."
                confidence = 0.85
                conclusion_type = ConclusionType.FACT
            elif any(term in lowered and term not in prior_lowered for term in self._guidance_terms):
                category = "guidance or outlook language changed"
                significance = "May alter expected revenue, margin, or catalyst assumptions."
                confidence = 0.72
            elif any(term in lowered and term not in prior_lowered for term in self._risk_terms):
                category = "risk, liquidity, or covenant language changed"
                significance = "May change downside, financing, or thesis-invalidation evidence."
                confidence = 0.76
            elif any(term in lowered and term not in prior_lowered for term in self._capital_terms):
                category = "capital-allocation language changed"
                significance = "May change cash-flow deployment or balance-sheet assumptions."
                confidence = 0.72
            conclusions.append(
                DocumentConclusion(
                    identifier=f"{current.identifier}:{section}",
                    section=section,
                    prior_passage=prior_passage,
                    current_passage=current_passage,
                    semantic_change=f"{category}; text similarity={similarity:.3f}",
                    investment_significance=significance,
                    confidence=confidence,
                    conclusion_type=conclusion_type,
                    exposures_affected=exposures,
                    numerical_claims=numbers,
                )
            )
        return DocumentChangeAnalysis(
            current_document_identifier=current.identifier,
            prior_document_identifier=prior.identifier if prior else None,
            conclusions=tuple(conclusions),
        )
