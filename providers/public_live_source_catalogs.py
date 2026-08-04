"""Composition of the base and supplemental governed public-source catalogs."""

from __future__ import annotations

from pathlib import Path

from providers.public_live_information import (
    PublicLiveSourceCatalog,
    load_public_live_source_catalog,
)


def load_operating_public_live_source_catalog(
    path: str | Path,
) -> PublicLiveSourceCatalog:
    """Load the base catalog plus an adjacent official-source expansion, if present."""

    catalog_path = Path(path)
    base = load_public_live_source_catalog(catalog_path)
    supplemental_path = catalog_path.with_name(
        f"{catalog_path.stem}_official_expansion{catalog_path.suffix}"
    )
    if not supplemental_path.exists():
        return base

    supplemental = load_public_live_source_catalog(supplemental_path)
    sources = base.sources + supplemental.sources
    identifiers = tuple(item.identifier for item in sources)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("public live source identifiers cannot repeat across catalogs")
    return PublicLiveSourceCatalog(
        identifier=f"{base.identifier}+{supplemental.identifier}",
        sources=sources,
    )


__all__ = ["load_operating_public_live_source_catalog"]
