"""Composition of the base and supplemental governed public-source catalogs."""

from __future__ import annotations

from pathlib import Path

from providers.public_live_information import (
    PublicLiveSourceCatalog,
    load_public_live_source_catalog,
)


_SUPPLEMENTAL_SUFFIXES = (
    "official_expansion",
    "free_depth",
)


def load_operating_public_live_source_catalog(
    path: str | Path,
) -> PublicLiveSourceCatalog:
    """Load the base catalog plus adjacent governed supplemental catalogs."""

    catalog_path = Path(path)
    catalogs = [load_public_live_source_catalog(catalog_path)]
    for suffix in _SUPPLEMENTAL_SUFFIXES:
        supplemental_path = catalog_path.with_name(
            f"{catalog_path.stem}_{suffix}{catalog_path.suffix}"
        )
        if supplemental_path.exists():
            catalogs.append(load_public_live_source_catalog(supplemental_path))

    sources = tuple(
        source
        for catalog in catalogs
        for source in catalog.sources
    )
    identifiers = tuple(item.identifier for item in sources)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("public live source identifiers cannot repeat across catalogs")
    return PublicLiveSourceCatalog(
        identifier="+".join(catalog.identifier for catalog in catalogs),
        sources=sources,
    )


__all__ = ["load_operating_public_live_source_catalog"]
