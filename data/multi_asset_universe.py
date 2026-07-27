"""Point-in-time universe construction for governed multi-asset expansion.

The existing Version 1 builder remains the active U.S. vertical slice. This
builder uses the same downstream universe contracts while correctly classifying
international listings, FX, and crypto and requiring the configured
RecommendationUniversePolicy to obtain an asset-class governance approval at the
snapshot timestamp.
"""

from __future__ import annotations

from datetime import datetime

from cio.models import CandidateAssetClass, CandidateInstrument
from cio.universe import RecommendationUniversePolicy, UniverseDisposition
from data.security import AssetClass
from data.security_master import (
    PointInTimeSecurityMasterSnapshot,
    SecurityMasterError,
    SecurityMasterMarketMetrics,
    SecurityMasterUniverseMembership,
    Version1UniverseConstituent,
    Version1UniverseExclusion,
    Version1UniverseSnapshot,
)


class MultiAssetUniverseBuilder:
    """Build one governed paper-recommendation universe across approved markets."""

    def __init__(
        self,
        policy: RecommendationUniversePolicy,
    ) -> None:
        if not isinstance(policy, RecommendationUniversePolicy):
            raise TypeError("policy must be RecommendationUniversePolicy")
        self.policy = policy

    def build(
        self,
        snapshot: PointInTimeSecurityMasterSnapshot,
        metrics: tuple[SecurityMasterMarketMetrics, ...],
        *,
        require_authoritative: bool = True,
    ) -> Version1UniverseSnapshot:
        if not isinstance(snapshot, PointInTimeSecurityMasterSnapshot):
            raise TypeError("snapshot must be PointInTimeSecurityMasterSnapshot")
        if not isinstance(metrics, tuple) or not all(
            isinstance(item, SecurityMasterMarketMetrics) for item in metrics
        ):
            raise TypeError(
                "metrics must contain SecurityMasterMarketMetrics values"
            )
        if require_authoritative:
            snapshot.coverage.require_authoritative()

        metric_by_instrument: dict[str, SecurityMasterMarketMetrics] = {}
        for item in metrics:
            if item.instrument_identifier in metric_by_instrument:
                raise ValueError("metrics cannot contain duplicate instruments")
            if item.observed_at > snapshot.as_of:
                raise ValueError("metrics observation cannot follow universe as_of")
            if item.available_at > snapshot.knowledge_cutoff:
                raise ValueError("metrics were unavailable at the knowledge cutoff")
            metric_by_instrument[item.instrument_identifier] = item

        constituents: list[Version1UniverseConstituent] = []
        exclusions: list[Version1UniverseExclusion] = []
        for record in snapshot.instruments:
            instrument = record.instrument
            try:
                listing = snapshot.active_primary_listing(instrument.instrument_id)
            except SecurityMasterError as error:
                exclusions.append(
                    Version1UniverseExclusion(
                        instrument_identifier=instrument.instrument_id,
                        symbol=None,
                        reasons=(str(error),),
                    )
                )
                continue
            metric = metric_by_instrument.get(instrument.instrument_id)
            if metric is None:
                exclusions.append(
                    Version1UniverseExclusion(
                        instrument_identifier=instrument.instrument_id,
                        symbol=listing.symbol,
                        reasons=(
                            "point-in-time liquidity and analytical coverage are unavailable",
                        ),
                    )
                )
                continue
            candidate = CandidateInstrument(
                instrument_id=instrument.instrument_id,
                symbol=listing.symbol,
                name=instrument.name,
                asset_class=_candidate_asset_class(
                    instrument.asset_class,
                    country_code=listing.country_code,
                    metric=metric,
                ),
                venue=listing.venue,
                country_code=listing.country_code,
                average_daily_dollar_volume=metric.average_daily_dollar_volume,
                data_age_hours=max(
                    0.0,
                    (snapshot.as_of - metric.observed_at).total_seconds() / 3600.0,
                ),
                analytical_coverage=metric.analytical_coverage,
                security_master_snapshot_identifier=snapshot.identifier,
                security_master_record_identifiers=tuple(
                    dict.fromkeys(
                        (
                            record.record_identifier,
                            listing.record_identifier,
                        )
                    )
                ),
                is_us_treasury=metric.is_us_treasury,
                effective_duration_years=metric.effective_duration_years,
            )
            assessment = self.policy.evaluate(candidate, as_of=snapshot.as_of)
            if assessment.disposition is not UniverseDisposition.DIRECT_RECOMMENDATION:
                exclusions.append(
                    Version1UniverseExclusion(
                        instrument_identifier=instrument.instrument_id,
                        symbol=listing.symbol,
                        reasons=assessment.reasons,
                    )
                )
                continue
            membership = SecurityMasterUniverseMembership(
                symbol=listing.symbol,
                eligible_from=max(record.effective_from, listing.effective_from),
                eligible_until=_earliest(
                    record.effective_until,
                    listing.effective_until,
                ),
                source_identifier=(
                    f"{snapshot.identifier}:{listing.record_identifier}:"
                    f"{metric.identifier}:{self.policy.version}:"
                    f"{assessment.asset_class_approval_identifier or 'core-v1'}"
                ),
            )
            constituents.append(
                Version1UniverseConstituent(
                    instrument=candidate,
                    assessment=assessment,
                    listing_identifier=listing.listing_identifier,
                    metrics_identifier=metric.identifier,
                    membership=membership,
                )
            )

        constituents.sort(
            key=lambda item: (
                item.instrument.asset_class.value,
                item.instrument.symbol,
                item.instrument.instrument_id,
            )
        )
        exclusions.sort(key=lambda item: (item.symbol or "", item.instrument_identifier))
        return Version1UniverseSnapshot(
            identifier=(
                f"multi-asset-universe:{snapshot.as_of.isoformat()}:"
                f"known:{snapshot.knowledge_cutoff.isoformat()}"
            ),
            as_of=snapshot.as_of,
            knowledge_cutoff=snapshot.knowledge_cutoff,
            security_master_snapshot_identifier=snapshot.identifier,
            policy_version=self.policy.version,
            authoritative=snapshot.coverage.authoritative,
            constituents=tuple(constituents),
            exclusions=tuple(exclusions),
        )


def _candidate_asset_class(
    asset_class: AssetClass,
    *,
    country_code: str,
    metric: SecurityMasterMarketMetrics,
) -> CandidateAssetClass:
    country = country_code.strip().upper()
    if asset_class is AssetClass.EQUITY:
        return (
            CandidateAssetClass.US_EQUITY
            if country == "US"
            else CandidateAssetClass.INTERNATIONAL_EQUITY
        )
    if asset_class is AssetClass.ETF:
        return (
            CandidateAssetClass.US_ETF
            if country == "US"
            else CandidateAssetClass.INTERNATIONAL_EQUITY
        )
    if asset_class is AssetClass.FIXED_INCOME and metric.is_us_treasury:
        return CandidateAssetClass.CASH_EQUIVALENT
    if asset_class is AssetClass.FIXED_INCOME:
        return CandidateAssetClass.FIXED_INCOME
    if asset_class is AssetClass.COMMODITY:
        return CandidateAssetClass.COMMODITY
    if asset_class is AssetClass.FX:
        return CandidateAssetClass.FX
    if asset_class is AssetClass.CRYPTO:
        return CandidateAssetClass.CRYPTO
    return CandidateAssetClass.OTHER


def _earliest(
    first: datetime | None,
    second: datetime | None,
) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


__all__ = ["MultiAssetUniverseBuilder"]
