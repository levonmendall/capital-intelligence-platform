"""Install truthful CME/Massive lineage at the legacy futures catalog boundary.

The legacy discovery function predates provider injection and labels every injected
point-in-time futures contract as Massive. CME-primary reference acquisition keeps the
same contract interface deliberately, so this narrow runtime adapter rewrites only the
reference-provider lineage on records whose source identifiers prove they came from CME.
Fallback Massive records remain unchanged.

No discovery membership, screening, ranking, CIO, construction, execution, or market
scope behavior is changed.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from operations import comprehensive_market_discovery_legacy as _legacy

_INSTALLED_MARKER = "_capital_intelligence_cme_lineage_adapter"
_ORIGINAL = _legacy._futures_catalog


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


setattr(_cme_aware_futures_catalog, _INSTALLED_MARKER, True)


def install_cme_futures_reference_lineage() -> None:
    current = _legacy._futures_catalog
    if bool(getattr(current, _INSTALLED_MARKER, False)):
        return
    _legacy._futures_catalog = _cme_aware_futures_catalog


__all__ = ["install_cme_futures_reference_lineage"]
