from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

from operations.global_public_catalog_reconciliation import reconcile_global_public_catalogs
from providers.global_public_security_catalog import GlobalPublicSecurityCatalogProvider
from providers.public_security_catalog import PublicCatalogSourceDefinition


class _Response:
    def __init__(self, content: bytes):
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1024):
        del chunk_size
        yield self.content


def _firds_zip() -> bytes:
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <root xmlns:a="urn:test">
      <a:FinInstrmGnlAttrbts><a:Id>GB0000000001</a:Id><a:FullNm>One PLC</a:FullNm><a:ShrtNm>ONE</a:ShrtNm><a:ClssfctnTp>ESXXXX</a:ClssfctnTp></a:FinInstrmGnlAttrbts>
      <a:FinInstrmGnlAttrbts><a:Id>GB0000000002</a:Id><a:FullNm>Two PLC</a:FullNm><a:ShrtNm>TWO</a:ShrtNm><a:ClssfctnTp>ESXXXX</a:ClssfctnTp></a:FinInstrmGnlAttrbts>
    </root>'''
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("firds.xml", xml)
    return output.getvalue()


def test_fca_firds_is_resumable_and_bounded(monkeypatch):
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PUBLIC_CATALOG_MAX_DOWNLOAD_BYTES", "1000000")
    source = PublicCatalogSourceDefinition(
        identifier="fca",
        source_name="FCA",
        endpoint="https://example.test/firds.zip",
        parser="fca_firds_zip_xml",
        venue="UK_MIFIR",
        country_code="GB",
        page_size=1,
    )
    payload = _firds_zip()
    provider = GlobalPublicSecurityCatalogProvider(
        source,
        http_get=lambda *args, **kwargs: _Response(payload),
        clock=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    first = provider.fetch_page()
    assert [item.isin for item in first.records] == ["GB0000000001"]
    assert first.complete is False
    assert first.next_cursor == "0:1"
    second = provider.fetch_page(cursor=first.next_cursor)
    assert [item.isin for item in second.records] == ["GB0000000002"]
    assert second.complete is True
    assert second.next_cursor is None


def test_reconciliation_never_grants_authority(tmp_path):
    root = tmp_path / "global_public_catalogs" / "esma" / "pages"
    root.mkdir(parents=True)
    (root / "page.json").write_text(
        json.dumps(
            {
                "source_identifier": "esma",
                "records": [
                    {
                        "isin": "DE0000000001",
                        "figi": "",
                        "venue": "XETR",
                        "country_code": "DE",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = reconcile_global_public_catalogs(
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        queue_limit=10,
        clock=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    payload = report.to_dict()
    assert payload["screening_authority"] is False
    assert payload["investment_authority"] is False
    assert payload["activation_performed"] is False
    assert report.openfigi_queue[0]["id_value"] == "DE0000000001"
