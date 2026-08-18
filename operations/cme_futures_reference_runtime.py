"""Install truthful CME/Massive lineage and granular futures supervision.

The legacy discovery function predates provider injection and labels every injected
point-in-time futures contract as Massive. CME-primary reference acquisition keeps the
same contract interface deliberately, so this runtime adapter rewrites only proven CME
lineage.

Production reference prequalification historically wrapped the complete futures
component in one 120-second worker. The executable CME provider is now root-checkpointed,
so this adapter also finishes that migration: executable providers with a configured
fallback delegate acquisition to the granular venue/root coordinator, and only the
obsolete futures-wide supervisor is bypassed. Directory and option component supervisors
remain unchanged.

No discovery membership, screening, ranking, CIO, construction, execution, or market
scope behavior is changed. The existing final configured-root completeness barrier
remains authoritative.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from operations import comprehensive_market_discovery_legacy as _legacy
from providers.cme_futures_reference_executable import (
    CmeExecutableFuturesReferenceProvider,
)

_LINEAGE_INSTALLED_MARKER = "_capital_intelligence_cme_lineage_adapter"
_PROVIDER_INSTALLED_MARKER = "_capital_intelligence_granular_futures_provider"
_SUPERVISOR_INSTALLED_MARKER = "_capital_intelligence_granular_futures_supervisor"
# Preserve the historical monkeypatch/test seam used by the lineage adapter.
_ORIGINAL = _legacy._futures_catalog
_ORIGINAL_EXECUTABLE_FUTURES_CONTRACTS = (
    CmeExecutableFuturesReferenceProvider.futures_contracts
)


def _cme_aware_futures_catalog(*args: Any, **kwargs: Any):
    records = _ORIGINAL(*args, **kwargs)
    result = []
    for record in records:
        source_identifier = str(getattr(record, "source_identifier", ""))
        if source_identifier.startswith("cme-fprf:"):
            record = replace(
                record,
                provider_kind="cme_fprf",
                provider_dataset="ftp/fprf/fixml",
            )
        result.append(record)
    return tuple(result)


setattr(_cme_aware_futures_catalog, _LINEAGE_INSTALLED_MARKER, True)


def _install_lineage_adapter() -> None:
    current = _legacy._futures_catalog
    if bool(getattr(current, _LINEAGE_INSTALLED_MARKER, False)):
        return
    _legacy._futures_catalog = _cme_aware_futures_catalog


def _install_granular_provider_adapter() -> None:
    current = CmeExecutableFuturesReferenceProvider.futures_contracts
    if bool(getattr(current, _PROVIDER_INSTALLED_MARKER, False)):
        return

    original = current

    def granular_futures_contracts(
        self: CmeExecutableFuturesReferenceProvider,
        *,
        as_of,
        product_codes=(),
        maximum_pages=20,
    ):
        # Internal CME-only providers used by the granular coordinator intentionally
        # have no fallback. Preserve their original executable behavior so the
        # coordinator can use the provider's cache and parser primitives directly.
        if self.fallback_provider is None:
            return original(
                self,
                as_of=as_of,
                product_codes=product_codes,
                maximum_pages=maximum_pages,
            )

        from operations.granular_futures_reference_prequalification import (
            GranularFuturesReferenceProvider,
        )

        coordinator = GranularFuturesReferenceProvider(values=self.values)
        result = coordinator.futures_contracts(
            as_of=as_of,
            product_codes=product_codes,
            maximum_pages=maximum_pages,
        )
        self._reference_telemetry = [
            dict(item) for item in coordinator.reference_telemetry
        ]
        self._reference_metadata = dict(coordinator.reference_metadata)
        return result

    setattr(granular_futures_contracts, _PROVIDER_INSTALLED_MARKER, True)
    CmeExecutableFuturesReferenceProvider.futures_contracts = granular_futures_contracts


def _install_reference_supervisor_adapter() -> None:
    # Imported lazily: this installer is invoked from reference prequalification after
    # that module has finished importing, avoiding a circular import.
    from operations import supervised_reference_prequalification as reference

    current = reference._run_component
    if bool(getattr(current, _SUPERVISOR_INSTALLED_MARKER, False)):
        return

    original = current

    def component_runner(
        *,
        values,
        component,
        provider,
        operation,
        return_value,
    ):
        if component == reference._FUTURES:
            # The operation itself is only a coordinator/final manifest publisher.
            # Every provider-facing CME venue and Massive root call beneath it is
            # independently supervised by GranularFuturesReferenceProvider.
            try:
                return operation()
            except reference._plane.ContinuousEvidencePlaneError:
                raise
            except Exception as error:
                failure_type = reference._failure_type(error)
                raise reference._plane.ContinuousEvidencePlaneError(
                    "granular futures reference coordinator incomplete; "
                    f"failure_type={failure_type}; component={component}; "
                    f"provider={provider}; {error}"
                ) from error
        return original(
            values=values,
            component=component,
            provider=provider,
            operation=operation,
            return_value=return_value,
        )

    setattr(component_runner, _SUPERVISOR_INSTALLED_MARKER, True)
    reference._run_component = component_runner


def install_cme_futures_reference_lineage() -> None:
    """Install CME lineage plus granular provider/supervision adapters idempotently."""

    _install_lineage_adapter()
    _install_granular_provider_adapter()
    _install_reference_supervisor_adapter()


__all__ = ["install_cme_futures_reference_lineage"]
