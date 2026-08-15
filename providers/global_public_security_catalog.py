"""Extended global public catalog provider with streamed FCA FIRDS support.

FCA FIRDS full/delta publications can be large compressed XML files.  This
provider streams the archive to bounded temporary disk and iterates XML records
incrementally.  Cursor state is row-based so continuous evidence maintenance can
resume without materializing the source in memory or invoking it from a CIO
request.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Mapping

from data.security import AssetClass, InstrumentType
from providers.public_security_catalog import (
    NormalizedPublicInstrument,
    PublicCatalogPage,
    PublicSecurityCatalogError,
    PublicSecurityCatalogProvider,
    _classify,
    _text,
)


def _local_name(tag: object) -> str:
    value = str(tag or "")
    return value.rsplit("}", 1)[-1] if "}" in value else value


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return _text(child.text)
    return ""


class GlobalPublicSecurityCatalogProvider(PublicSecurityCatalogProvider):
    """Public catalog provider with disk-bounded compressed regulator parsing."""

    def _download_to_disk(self) -> tuple[Path, str, tempfile.TemporaryDirectory[str]]:
        response = self._http_get(
            self.source.endpoint,
            headers={"Accept": "application/zip,application/octet-stream,application/xml"},
            timeout=self.timeout,
            stream=True,
        )
        response.raise_for_status()
        maximum = int(
            os.getenv(
                "CAPITAL_INTELLIGENCE_PUBLIC_CATALOG_MAX_DOWNLOAD_BYTES",
                "300000000",
            )
        )
        if maximum < 1_000_000 or maximum > 1_000_000_000:
            raise PublicSecurityCatalogError(
                "public catalog download budget must be between 1MB and 1GB"
            )
        temporary = tempfile.TemporaryDirectory(prefix="capital-intelligence-firds-")
        path = Path(temporary.name) / "firds-download"
        digest = hashlib.sha256()
        total = 0
        with path.open("wb") as handle:
            iterator = getattr(response, "iter_content", None)
            chunks = iterator(chunk_size=1024 * 1024) if callable(iterator) else (bytes(response.content),)
            for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if total > maximum:
                    temporary.cleanup()
                    raise PublicSecurityCatalogError(
                        "public catalog download exceeded bounded disk budget"
                    )
                digest.update(chunk)
                handle.write(chunk)
        if total == 0:
            temporary.cleanup()
            raise PublicSecurityCatalogError("public catalog download was empty")
        return path, digest.hexdigest(), temporary

    @staticmethod
    def _generic_attributes(element: ET.Element) -> Mapping[str, str] | None:
        if _local_name(element.tag) != "FinInstrmGnlAttrbts":
            return None
        isin = _child_text(element, "Id")
        full_name = _child_text(element, "FullNm")
        short_name = _child_text(element, "ShrtNm")
        cfi = _child_text(element, "ClssfctnTp")
        if not isin:
            return None
        return {
            "isin": isin,
            "name": full_name or short_name or isin,
            "symbol": short_name or isin,
            "cfi": cfi,
        }

    def _iter_firds_xml(self, handle: Any, *, skip: int):
        seen = 0
        for _event, element in ET.iterparse(handle, events=("end",)):
            attributes = self._generic_attributes(element)
            if attributes is None:
                continue
            if seen < skip:
                seen += 1
                element.clear()
                continue
            yield seen, attributes
            seen += 1
            element.clear()

    def _normalize_firds(self, values: Mapping[str, str]) -> NormalizedPublicInstrument:
        isin = _text(values.get("isin"))
        name = _text(values.get("name")) or isin
        symbol = _text(values.get("symbol")) or isin
        cfi = _text(values.get("cfi"))
        asset_class, instrument_type = _classify(cfi)
        return NormalizedPublicInstrument(
            source_identifier=f"{self.source.identifier}:{isin}",
            provider_instrument_identifier=isin,
            name=name,
            symbol=symbol,
            venue=self.source.venue,
            country_code=self.source.country_code,
            isin=isin if len(isin) == 12 else "",
            cfi=cfi,
            asset_class=asset_class,
            instrument_type=instrument_type,
        )

    def _fetch_fca_firds_zip_xml(self, *, cursor: str | None) -> PublicCatalogPage:
        start = int(cursor or "0")
        if start < 0:
            raise PublicSecurityCatalogError("FCA FIRDS cursor cannot be negative")
        path, archive_hash, temporary = self._download_to_disk()
        try:
            rows: list[NormalizedPublicInstrument] = []
            consumed = start
            source_complete = True
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    members = sorted(
                        member
                        for member in archive.namelist()
                        if member.casefold().endswith(".xml")
                    )
                    if not members:
                        raise PublicSecurityCatalogError(
                            "FCA FIRDS archive contained no XML member"
                        )
                    # FCA publishes one logical full/delta file per archive in the
                    # ordinary case. Multiple members are processed as one stream.
                    logical_index = 0
                    for member in members:
                        with archive.open(member) as xml_handle:
                            for _, values in self._iter_firds_xml(
                                xml_handle, skip=max(0, start - logical_index)
                            ):
                                rows.append(self._normalize_firds(values))
                                logical_index += 1
                                consumed = logical_index
                                if len(rows) >= self.source.page_size:
                                    source_complete = False
                                    break
                        if not source_complete:
                            break
            else:
                with path.open("rb") as xml_handle:
                    for index, values in self._iter_firds_xml(xml_handle, skip=start):
                        rows.append(self._normalize_firds(values))
                        consumed = index + 1
                        if len(rows) >= self.source.page_size:
                            source_complete = False
                            break
            if not rows and start == 0:
                raise PublicSecurityCatalogError(
                    "FCA FIRDS file contained no normalizable instruments"
                )
            # The archive hash binds every page to the exact upstream publication;
            # the cursor suffix prevents different pages from colliding downstream.
            page_hash = hashlib.sha256(
                f"{archive_hash}:{start}:{consumed}".encode("utf-8")
            ).hexdigest()
            return PublicCatalogPage(
                source_identifier=self.source.identifier,
                retrieved_at=self._clock(),
                records=tuple(rows),
                next_cursor=None if source_complete else str(consumed),
                complete=source_complete,
                content_hash=page_hash,
            )
        finally:
            temporary.cleanup()


__all__ = ["GlobalPublicSecurityCatalogProvider"]
