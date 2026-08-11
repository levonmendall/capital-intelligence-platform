"""Point-in-time coverage audit for global opportunity rotation.

This audit cannot create missing subscriptions or provider entitlements. It makes those
gaps explicit by measuring which economic opportunity domains actually reached the
reviewed point-in-time set with market, evidence and forward-intelligence coverage.
It is evaluation/readiness only and has no investment authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from portfolio.global_rotation_models import GlobalOpportunityDomain, opportunity_domain


_DEFAULT_REQUIRED_DOMAINS = (
    GlobalOpportunityDomain.EQUITY,
    GlobalOpportunityDomain.FIXED_INCOME,
    GlobalOpportunityDomain.CREDIT,
    GlobalOpportunityDomain.CURRENCY,
    GlobalOpportunityDomain.COMMODITY,
    GlobalOpportunityDomain.CRYPTO,
)


@dataclass(frozen=True, slots=True)
class MarketDomainCoverage:
    domain: GlobalOpportunityDomain
    candidate_count: int
    complete_evidence_count: int
    forward_intelligence_count: int
    liquid_candidate_count: int
    coverage_ratio: float
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "candidate_count": self.candidate_count,
            "complete_evidence_count": self.complete_evidence_count,
            "forward_intelligence_count": self.forward_intelligence_count,
            "liquid_candidate_count": self.liquid_candidate_count,
            "coverage_ratio": self.coverage_ratio,
            "ready": self.ready,
        }


@dataclass(frozen=True, slots=True)
class GlobalMarketCoverageReport:
    as_of: datetime
    domains: tuple[MarketDomainCoverage, ...]
    missing_required_domains: tuple[str, ...]
    reviewed_candidate_count: int
    evidence_ready_ratio: float
    forward_intelligence_ratio: float
    all_required_domains_present: bool
    globally_rotation_ready: bool
    limitations: tuple[str, ...]
    schema_version: str = "global-market-coverage.v1"
    investment_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "domains": [item.to_dict() for item in self.domains],
            "missing_required_domains": list(self.missing_required_domains),
            "reviewed_candidate_count": self.reviewed_candidate_count,
            "evidence_ready_ratio": self.evidence_ready_ratio,
            "forward_intelligence_ratio": self.forward_intelligence_ratio,
            "all_required_domains_present": self.all_required_domains_present,
            "globally_rotation_ready": self.globally_rotation_ready,
            "limitations": list(self.limitations),
            "investment_authority": False,
            "performance_claim_authority": False,
        }


def build_global_market_coverage_report(
    *,
    candidates: Sequence[object],
    specialist_contexts: Sequence[object],
    as_of: datetime,
    required_domains: tuple[GlobalOpportunityDomain, ...] = _DEFAULT_REQUIRED_DOMAINS,
    minimum_domain_evidence_ratio: float = 0.70,
) -> GlobalMarketCoverageReport:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not 0.0 <= minimum_domain_evidence_ratio <= 1.0:
        raise ValueError("minimum_domain_evidence_ratio must be between zero and one")
    contexts = {
        str(getattr(item, "candidate_identifier")): item for item in specialist_contexts
    }
    grouped: dict[GlobalOpportunityDomain, list[object]] = {}
    for candidate in candidates:
        grouped.setdefault(opportunity_domain(candidate), []).append(candidate)

    domain_reports: list[MarketDomainCoverage] = []
    for domain in GlobalOpportunityDomain:
        values = grouped.get(domain, [])
        complete = 0
        forward = 0
        liquid = 0
        for candidate in values:
            quality = getattr(candidate, "evidence_quality", None)
            if (
                quality is not None
                and float(getattr(quality, "score", 0.0)) >= 0.70
                and float(getattr(quality, "ceiling", 0.0)) >= 0.50
            ):
                complete += 1
            if float(getattr(candidate, "liquidity_score", 0.0)) >= 0.70:
                liquid += 1
            context = contexts.get(str(getattr(candidate, "identifier")))
            if context is not None and getattr(context, "forward_intelligence", None) is not None:
                forward += 1
        count = len(values)
        evidence_ratio = 0.0 if count == 0 else complete / count
        forward_ratio = 0.0 if count == 0 else forward / count
        liquidity_ratio = 0.0 if count == 0 else liquid / count
        combined = 0.50 * evidence_ratio + 0.30 * forward_ratio + 0.20 * liquidity_ratio
        ready = (
            count > 0
            and evidence_ratio >= minimum_domain_evidence_ratio
            and liquidity_ratio >= minimum_domain_evidence_ratio
        )
        domain_reports.append(
            MarketDomainCoverage(
                domain=domain,
                candidate_count=count,
                complete_evidence_count=complete,
                forward_intelligence_count=forward,
                liquid_candidate_count=liquid,
                coverage_ratio=round(combined, 8),
                ready=ready,
            )
        )

    missing = tuple(
        domain.value for domain in required_domains if not grouped.get(domain)
    )
    reviewed = len(candidates)
    complete_total = sum(item.complete_evidence_count for item in domain_reports)
    forward_total = sum(item.forward_intelligence_count for item in domain_reports)
    evidence_ready_ratio = 0.0 if reviewed == 0 else complete_total / reviewed
    forward_ratio = 0.0 if reviewed == 0 else forward_total / reviewed
    required_report = {item.domain: item for item in domain_reports}
    all_present = not missing
    all_ready = all(required_report[item].ready for item in required_domains)
    limitations: list[str] = []
    if missing:
        limitations.append(
            "No reviewed candidate reached the CIO opportunity set for: " + ", ".join(missing)
        )
    for item in required_domains:
        report = required_report[item]
        if report.candidate_count and not report.ready:
            limitations.append(
                f"{item.value} reached review but evidence/liquidity coverage is below the governed readiness ratio."
            )
    if forward_ratio < 0.70 and reviewed:
        limitations.append(
            "Less than 70% of reviewed candidates contain forward-intelligence bundles; prospective leadership coverage is incomplete."
        )
    if not limitations:
        limitations.append(
            "Observed decision-set coverage is complete for the required domains; this does not prove exchange/provider entitlement completeness outside the observed set."
        )
    return GlobalMarketCoverageReport(
        as_of=as_of,
        domains=tuple(domain_reports),
        missing_required_domains=missing,
        reviewed_candidate_count=reviewed,
        evidence_ready_ratio=round(evidence_ready_ratio, 8),
        forward_intelligence_ratio=round(forward_ratio, 8),
        all_required_domains_present=all_present,
        globally_rotation_ready=bool(all_present and all_ready and forward_ratio >= 0.70),
        limitations=tuple(limitations),
    )


__all__ = [
    "GlobalMarketCoverageReport",
    "MarketDomainCoverage",
    "build_global_market_coverage_report",
]
