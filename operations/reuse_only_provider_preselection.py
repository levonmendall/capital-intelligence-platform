"""Reuse-only exact-epoch provider publication guard for comprehensive lane children.

Provider network acquisition is owned by the bounded early overlap path. The serialized
transactional comprehensive lane may only validate and consume the clean canonical
publication for its exact request. Missing, corrupt, stale, count-mismatched, or limited
provider evidence fails closed here and can never trigger a late provider-network fallback.

This module changes only provider acquisition ownership. It has no evidence, candidate,
sizing, construction, execution, CIO, or real-money authority and does not alter freshness,
market scope, screening, strategy, or portfolio construction.
"""

from __future__ import annotations

from operations import transactional_comprehensive_discovery_lane as _canonical


_PUBLICATION_ATTRIBUTE = "ensure_" + "provider_preselection_publication"


def reuse_only_provider_publication(
    catalogs,
    *,
    as_of,
    policy=None,
    **_ignored,
):
    """Return a clean exact-epoch publication without invoking any provider."""

    publication = _canonical._publication
    timestamp = publication._core._aware(as_of, field_name="as_of")
    resolved = policy or publication.ComprehensiveMarketDiscoveryPolicy()
    records = publication._records_for_lane(catalogs)
    if not records:
        raise publication.ProviderPreselectionPublicationError(
            "provider preselection publication requires a nonempty catalog"
        )
    fingerprint = publication._streaming_catalog_fingerprint(records)
    path = publication._core._publication_path(resolved)
    freshness_days = int(getattr(resolved, "preselection_freshness_days", 3))
    existing = publication._existing_result_bounded(
        path,
        as_of=timestamp,
        fingerprint=fingerprint,
        catalog_count=len(records),
        freshness_days=freshness_days,
    )
    if existing is None:
        raise publication.ProviderPreselectionPublicationError(
            "epoch-scoped provider publication is unavailable or invalid; "
            "serialized comprehensive lane refuses late provider reacquisition"
        )
    limitations = tuple(
        str(item)
        for item in getattr(existing, "limitations", ())
        if str(item).strip()
    )
    if limitations:
        raise publication.ProviderPreselectionPublicationError(
            "epoch-scoped provider publication contains limitations; "
            "serialized comprehensive lane refuses degraded provider evidence"
        )
    return existing


def install_reuse_only_provider_publication() -> None:
    """Install the provider-free validator into the canonical transaction module."""

    setattr(
        _canonical._publication,
        _PUBLICATION_ATTRIBUTE,
        reuse_only_provider_publication,
    )


__all__ = [
    "install_reuse_only_provider_publication",
    "reuse_only_provider_publication",
]
