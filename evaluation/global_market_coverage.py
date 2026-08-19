"""Point-in-time coverage audit for global opportunity rotation.

This audit cannot create missing subscriptions or provider entitlements. It makes those
gaps explicit by measuring which economic opportunity domains *and geographic regions*
actually reached the reviewed point-in-time set with market, evidence and
forward-intelligence coverage. It is evaluation/readiness only and has no investment
authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Sequence

from portfolio.global_rotation_models import GlobalOpportunityDomain, opportunity_domain


# Preserve the original global-rotation readiness contract: the six core economic
# domains must be represented and ready. Broader domains remain explicitly measured
# below as accountability coverage, but do not silently redefine this established
# readiness signal.
_DEFAULT_REQUIRED_DOMAINS = (
    GlobalOpportunityDomain.EQUITY,
    GlobalOpportunityDomain.FIXED_INCOME,
    GlobalOpportunityDomain.CREDIT,
    GlobalOpportunityDomain.CURRENCY,
    GlobalOpportunityDomain.COMMODITY,
    GlobalOpportunityDomain.CRYPTO,
)

_ACCOUNTABILITY_DOMAINS = (
    *_DEFAULT_REQUIRED_DOMAINS,
    GlobalOpportunityDomain.REAL_ESTATE,
    GlobalOpportunityDomain.VOLATILITY,
    GlobalOpportunityDomain.ALTERNATIVE,
)


class GlobalOpportunityRegion(str, Enum):
    NORTH_AMERICA = "north_america"
    EUROPE = "europe"
    JAPAN = "japan"
    DEVELOPED_ASIA_PACIFIC = "developed_asia_pacific"
    EMERGING_MARKETS = "emerging_markets"
    GLOBAL_OR_NON_GEOGRAPHIC = "global_or_non_geographic"
    OTHER = "other"


_DEFAULT_REQUIRED_REGIONS = (
    GlobalOpportunityRegion.NORTH_AMERICA,
    GlobalOpportunityRegion.EUROPE,
    GlobalOpportunityRegion.JAPAN,
    GlobalOpportunityRegion.DEVELOPED_ASIA_PACIFIC,
    GlobalOpportunityRegion.EMERGING_MARKETS,
)

_EUROPE = frozenset(
    {
        "AT", "BE", "CH", "CZ", "DE", "DK", "ES", "FI", "FR", "GB", "GR",
        "IE", "IT", "NL", "NO", "PL", "PT", "SE", "TR",
    }
)
_DEVELOPED_ASIA_PACIFIC = frozenset(
    {"AU", "HK", "KR", "NZ", "SG", "TW"}
)
_EMERGING = frozenset(
    {
        "AR", "BR", "CL", "CN", "CO", "EG", "ID", "IN", "MX", "MY", "PE",
        "PH", "PL", "SA", "TH", "TR", "VN", "ZA",
    }
)


def opportunity_region(candidate: object) -> GlobalOpportunityRegion:
    instrument = getattr(candidate, "instrument", candidate)
    country = str(getattr(instrument, "country_code", "")).strip().upper()
    domain = opportunity_domain(candidate)
    if country in {"US", "CA"}:
        return GlobalOpportunityRegion.NORTH_AMERICA
    if country == "JP":
        return GlobalOpportunityRegion.JAPAN
    if country in _EUROPE:
        return GlobalOpportunityRegion.EUROPE
    if country in _DEVELOPED_ASIA_PACIFIC:
        return GlobalOpportunityRegion.DEVELOPED_ASIA_PACIFIC
    if country in _EMERGING:
        return GlobalOpportunityRegion.EMERGING_MARKETS
    if domain in {
        GlobalOpportunityDomain.CURRENCY,
        GlobalOpportunityDomain.COMMODITY,
        GlobalOpportunityDomain.CRYPTO,
        GlobalOpportunityDomain.VOLATILITY,
        GlobalOpportunityDomain.ALTERNATIVE,
        GlobalOpportunityDomain.CASH,
    }:
        return GlobalOpportunityRegion.GLOBAL_OR_NON_GEOGRAPHIC
    return GlobalOpportunityRegion.OTHER


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
class RegionalMarketCoverage:
    region: GlobalOpportunityRegion
    candidate_count: int
    complete_evidence_count: int
    forward_intelligence_count: int
    liquid_candidate_count: int
    coverage_ratio: float
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": self.region.value,
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
    regions: tuple[RegionalMarketCoverage, ...] = ()
    missing_required_regions: tuple[str, ...] = ()
    regional_coverage_ratio: float = 0.0
    all_required_regions_present: bool = False
    regional_rotation_ready: bool = False
    schema_version: str = "global-market-coverage.v2"
    investment_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "domains": [item.to_dict() for item in self.domains],
            "regions": [item.to_dict() for item in self.regions],
            "missing_required_domains": list(self.missing_required_domains),
            "missing_required_regions": list(self.missing_required_regions),
            "reviewed_candidate_count": self.reviewed_candidate_count,
            "evidence_ready_ratio": self.evidence_ready_ratio,
            "forward_intelligence_ratio": self.forward_intelligence_ratio,
            "regional_coverage_ratio": self.regional_coverage_ratio,
            "all_required_domains_present": self.all_required_domains_present,
            "all_required_regions_present": self.all_required_regions_present,
            "regional_rotation_ready": self.regional_rotation_ready,
            "globally_rotation_ready": self.globally_rotation_ready,
            "limitations": list(self.limitations),
            "investment_authority": False,
            "performance_claim_authority": False,
        }


def _coverage_counts(values: Sequence[object], contexts: dict[str, object]):
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
    return complete, forward, liquid


def _ratio(count: int, numerator: int) -> float:
    return 0.0 if count == 0 else numerator / count


def build_global_market_coverage_report(
    *,
    candidates: Sequence[object],
    specialist_contexts: Sequence[object],
    as_of: datetime,
    required_domains: tuple[GlobalOpportunityDomain, ...] = _DEFAULT_REQUIRED_DOMAINS,
    required_regions: tuple[GlobalOpportunityRegion, ...] = _DEFAULT_REQUIRED_REGIONS,
    minimum_domain_evidence_ratio: float = 0.70,
    minimum_region_evidence_ratio: float = 0.60,
) -> GlobalMarketCoverageReport:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    for name, value in (
        ("minimum_domain_evidence_ratio", minimum_domain_evidence_ratio),
        ("minimum_region_evidence_ratio", minimum_region_evidence_ratio),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between zero and one")
    contexts = {
        str(getattr(item, "candidate_identifier")): item for item in specialist_contexts
    }

    grouped_domains: dict[GlobalOpportunityDomain, list[object]] = {}
    grouped_regions: dict[GlobalOpportunityRegion, list[object]] = {}
    for candidate in candidates:
        grouped_domains.setdefault(opportunity_domain(candidate), []).append(candidate)
        grouped_regions.setdefault(opportunity_region(candidate), []).append(candidate)

    domain_reports: list[MarketDomainCoverage] = []
    for domain in GlobalOpportunityDomain:
        values = grouped_domains.get(domain, [])
        complete, forward, liquid = _coverage_counts(values, contexts)
        count = len(values)
        evidence_ratio = _ratio(count, complete)
        forward_ratio = _ratio(count, forward)
        liquidity_ratio = _ratio(count, liquid)
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

    region_reports: list[RegionalMarketCoverage] = []
    for region in GlobalOpportunityRegion:
        values = grouped_regions.get(region, [])
        complete, forward, liquid = _coverage_counts(values, contexts)
        count = len(values)
        evidence_ratio = _ratio(count, complete)
        forward_ratio = _ratio(count, forward)
        liquidity_ratio = _ratio(count, liquid)
        combined = 0.50 * evidence_ratio + 0.30 * forward_ratio + 0.20 * liquidity_ratio
        ready = (
            count > 0
            and evidence_ratio >= minimum_region_evidence_ratio
            and liquidity_ratio >= minimum_region_evidence_ratio
        )
        region_reports.append(
            RegionalMarketCoverage(
                region=region,
                candidate_count=count,
                complete_evidence_count=complete,
                forward_intelligence_count=forward,
                liquid_candidate_count=liquid,
                coverage_ratio=round(combined, 8),
                ready=ready,
            )
        )

    missing_domains = tuple(
        domain.value for domain in required_domains if not grouped_domains.get(domain)
    )
    missing_regions = tuple(
        region.value for region in required_regions if not grouped_regions.get(region)
    )
    missing_accountability_domains = tuple(
        domain.value
        for domain in _ACCOUNTABILITY_DOMAINS
        if domain not in required_domains and not grouped_domains.get(domain)
    )
    reviewed = len(candidates)
    complete_total = sum(item.complete_evidence_count for item in domain_reports)
    forward_total = sum(item.forward_intelligence_count for item in domain_reports)
    evidence_ready_ratio = _ratio(reviewed, complete_total)
    forward_ratio = _ratio(reviewed, forward_total)

    domain_by_key = {item.domain: item for item in domain_reports}
    region_by_key = {item.region: item for item in region_reports}
    all_domains_present = not missing_domains
    all_domains_ready = all(domain_by_key[item].ready for item in required_domains)
    all_regions_present = not missing_regions
    all_regions_ready = all(region_by_key[item].ready for item in required_regions)
    regional_ratio = (
        0.0
        if not required_regions
        else sum(region_by_key[item].coverage_ratio for item in required_regions)
        / len(required_regions)
    )

    limitations: list[str] = []
    if missing_domains:
        limitations.append(
            "No reviewed candidate reached the CIO opportunity set for required asset domains: "
            + ", ".join(missing_domains)
        )
    if missing_accountability_domains:
        limitations.append(
            "Broader opportunity-accountability domains were not observed in the reviewed set: "
            + ", ".join(missing_accountability_domains)
        )
    if missing_regions:
        limitations.append(
            "No reviewed candidate reached the CIO opportunity set for geographic regions: "
            + ", ".join(missing_regions)
        )
    for item in required_domains:
        report = domain_by_key[item]
        if report.candidate_count and not report.ready:
            limitations.append(
                f"{item.value} reached review but evidence/liquidity coverage is below the governed readiness ratio."
            )
    for item in required_regions:
        report = region_by_key[item]
        if report.candidate_count and not report.ready:
            limitations.append(
                f"{item.value} reached review but regional evidence/liquidity coverage is below the governed readiness ratio."
            )
    if forward_ratio < 0.70 and reviewed:
        limitations.append(
            "Less than 70% of reviewed candidates contain forward-intelligence bundles; prospective leadership coverage is incomplete."
        )
    if not limitations:
        limitations.append(
            "Observed decision-set coverage is complete across required asset domains and geographic regions; this does not prove exchange/provider entitlement completeness outside the observed set."
        )

    regional_ready = bool(all_regions_present and all_regions_ready)
    return GlobalMarketCoverageReport(
        as_of=as_of,
        domains=tuple(domain_reports),
        regions=tuple(region_reports),
        missing_required_domains=missing_domains,
        missing_required_regions=missing_regions,
        reviewed_candidate_count=reviewed,
        evidence_ready_ratio=round(evidence_ready_ratio, 8),
        forward_intelligence_ratio=round(forward_ratio, 8),
        regional_coverage_ratio=round(regional_ratio, 8),
        all_required_domains_present=all_domains_present,
        all_required_regions_present=all_regions_present,
        regional_rotation_ready=regional_ready,
        globally_rotation_ready=bool(
            all_domains_present
            and all_domains_ready
            and forward_ratio >= 0.70
        ),
        limitations=tuple(limitations),
    )


__all__ = [
    "GlobalMarketCoverageReport",
    "GlobalOpportunityRegion",
    "MarketDomainCoverage",
    "RegionalMarketCoverage",
    "build_global_market_coverage_report",
    "opportunity_region",
]
