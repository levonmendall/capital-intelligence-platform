"""Governed provider-preselection publication wrapper.

The certified runtime implementation is retained verbatim in
``_provider_preselection_publication_runtime_core``.  This wrapper adds one bounded
compatibility path required by comprehensive all-market discovery: an EODHD-directory
crypto record that does not receive a substantive exchange-bulk factor signal may use
the already-certified provider-native historical probe.  Bulk evidence remains
preferred, ordinary directory equities do not gain per-symbol fallback I/O, and every
fallback signal still requires real provider evidence.

No screening threshold, market admission rule, CIO authority, construction rule, or
execution control is changed.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Mapping, Sequence

from cio import CandidateAssetClass
from operations import _provider_preselection_publication_runtime_core as _core


ProviderPreselectionPublicationError = _core.ProviderPreselectionPublicationError
ProviderPreselectionPublicationResult = _core.ProviderPreselectionPublicationResult
ComprehensiveMarketDiscoveryPolicy = _core.ComprehensiveMarketDiscoveryPolicy
DiscoveryCatalogRecord = _core.DiscoveryCatalogRecord
DiscoveryMarketFeatures = _core.DiscoveryMarketFeatures

# Keep these mutable aliases at the public module boundary because the existing tests and
# diagnostic harness intentionally monkeypatch them.  ``_sync_core_overrides`` forwards
# those substitutions before the preserved core executes.
default_market_probe = _core.default_market_probe
record_manual_cio_diagnostic_progress = _core.record_manual_cio_diagnostic_progress


def _sync_core_overrides() -> None:
    _core.default_market_probe = default_market_probe
    _core.record_manual_cio_diagnostic_progress = record_manual_cio_diagnostic_progress


def _provider_history_features(
    records: Sequence[DiscoveryCatalogRecord],
    *,
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy,
    market_probe,
) -> tuple[Mapping[str, DiscoveryMarketFeatures], tuple[str, ...]]:
    """Collect bounded provider-native history for unresolved crypto bulk records."""

    if not records:
        return {}, ()
    record_manual_cio_diagnostic_progress(
        "provider_preselection_fallback_probe",
        metrics={"catalog_records": len(records)},
    )
    limitations: list[str] = []
    try:
        if market_probe is not None:
            features = market_probe(records, as_of, policy)
        else:
            batches = _core._fallback_probe_batches(records)

            def collect_batch(batch):
                return default_market_probe(
                    batch,
                    as_of,
                    policy,
                    maximum_workers=1,
                )

            if len(batches) > 1:
                with ThreadPoolExecutor(
                    max_workers=min(_core._MAX_PROVIDER_IO_WORKERS, len(batches)),
                    thread_name_prefix="provider-preselection-crypto-fallback",
                ) as executor:
                    partial_features = tuple(executor.map(collect_batch, batches))
            else:
                partial_features = tuple(map(collect_batch, batches))
            merged: dict[str, DiscoveryMarketFeatures] = {}
            for record in records:
                for partial in partial_features:
                    if record.symbol in partial:
                        merged[record.symbol] = partial[record.symbol]
                        break
            features = merged
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        limitations.append(
            "provider-native crypto factor fallback failed: "
            f"{type(error).__name__}"
        )
        features = {}
    record_manual_cio_diagnostic_progress(
        "provider_preselection_fallback_probe_complete",
        metrics={"evidence_complete_records": len(features)},
    )
    return features, tuple(limitations)


def _payload_from_result(result: ProviderPreselectionPublicationResult) -> dict[str, object]:
    try:
        payload = json.loads(result.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProviderPreselectionPublicationError(
            "provider preselection publication could not be reopened for bounded "
            "crypto fallback"
        ) from error
    if not isinstance(payload, Mapping):
        raise ProviderPreselectionPublicationError(
            "provider preselection publication is invalid during bounded crypto fallback"
        )
    return dict(payload)


def ensure_provider_preselection_publication(
    catalogs: Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]],
    *,
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
    http_get=_core.requests.get,
    market_probe=None,
) -> ProviderPreselectionPublicationResult:
    """Build the governed publication, then fill only unresolved grouped crypto history."""

    _sync_core_overrides()
    timestamp = _core._aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    records = _core._flatten_catalogs(catalogs)
    grouped_crypto = tuple(
        record
        for record in records
        if record.asset_class is CandidateAssetClass.CRYPTO
        and _core._source_exchange_and_code(record) is not None
    )

    initial_result: ProviderPreselectionPublicationResult | None = None
    initial_error: ProviderPreselectionPublicationError | None = None
    payload: dict[str, object] = {}
    try:
        initial_result = _core.ensure_provider_preselection_publication(
            catalogs,
            as_of=timestamp,
            policy=resolved,
            http_get=http_get,
            market_probe=market_probe,
        )
        payload = _payload_from_result(initial_result)
    except ProviderPreselectionPublicationError as error:
        if "no substantive provider factor signal" not in str(error):
            raise
        initial_error = error

    existing_signals = payload.get("signals", {})
    if not isinstance(existing_signals, Mapping):
        existing_signals = {}
    unresolved_crypto = tuple(
        record for record in grouped_crypto if record.symbol not in existing_signals
    )
    if not unresolved_crypto:
        if initial_result is not None:
            return initial_result
        assert initial_error is not None
        raise initial_error

    features, fallback_limitations = _provider_history_features(
        unresolved_crypto,
        as_of=timestamp,
        policy=resolved,
        market_probe=market_probe,
    )
    fallback_signals: dict[str, object] = {}
    fallback_sources: list[str] = []
    for record in unresolved_crypto:
        item = features.get(record.symbol)
        if item is None:
            continue
        fallback_signals[record.symbol] = _core._feature_signal(record, item)
        fallback_sources.extend(item.evidence_identifiers)

    if not fallback_signals and initial_result is None:
        assert initial_error is not None
        raise initial_error

    fingerprint = _core._catalog_fingerprint(records)
    path = _core._publication_path(resolved)
    signals = dict(existing_signals)
    signals.update(fallback_signals)
    limitations = list(payload.get("limitations", ())) if payload else []
    limitations.extend(fallback_limitations)
    if fallback_signals:
        limitations.append(
            "EODHD exchange-bulk evidence did not yield a substantive factor signal "
            f"for {len(fallback_signals)} crypto record(s); bounded provider-native "
            "history supplied the missing provider factors."
        )

    prior_sources = payload.get("source_identifiers", ()) if payload else ()
    runtime_source = (
        f"provider-preselection-runtime:{_core._PUBLICATION_METHOD_VERSION}:"
        f"{fingerprint}"
    )
    source_identifiers = tuple(
        dict.fromkeys(
            (
                runtime_source,
                *(
                    item
                    for item in prior_sources
                    if isinstance(item, str) and item.strip() and item != runtime_source
                ),
                *fallback_sources,
            )
        )
    )
    updated: dict[str, object] = dict(payload)
    updated.update(
        {
            "schema_version": _core.PROVIDER_PRESELECTION_SCHEMA,
            "methodology_version": _core._PUBLICATION_METHOD_VERSION,
            "available_at": timestamp.isoformat(),
            "catalog_fingerprint": fingerprint,
            "catalog_count": len(records),
            "signal_count": len(signals),
            "source_identifiers": list(source_identifiers),
            "limitations": list(dict.fromkeys(str(item) for item in limitations)),
            "signals": signals,
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
    )
    _core._atomic_write(path, updated)
    return ProviderPreselectionPublicationResult(
        path=path,
        available_at=timestamp,
        catalog_count=len(records),
        signal_count=len(signals),
        reused=False,
        source_identifiers=source_identifiers,
        limitations=tuple(dict.fromkeys(str(item) for item in limitations)),
    )


def __getattr__(name: str):
    return getattr(_core, name)


__all__ = [
    "ProviderPreselectionPublicationError",
    "ProviderPreselectionPublicationResult",
    "ensure_provider_preselection_publication",
]
