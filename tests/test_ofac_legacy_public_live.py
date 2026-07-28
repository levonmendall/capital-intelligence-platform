from __future__ import annotations

from datetime import datetime, timezone

from data.decision_information import InformationSourceType, PortfolioImpactChannel
from providers.public_live_information import (
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
)
from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider,
)


class FakeResponse:
    content = (
        b'12345,"Example Legacy Entity",Entity,TEST-PROGRAM,,,,,,,,'
        b'"Legacy official export"\n'
    )
    text = content.decode("utf-8")

    def raise_for_status(self) -> None:
        return None


def test_headerless_ofac_export_keeps_first_designation() -> None:
    source = PublicLiveSourceDefinition(
        identifier="ofac:test",
        source_name="OFAC Test",
        parser="ofac_csv",
        endpoint="https://example.test/sdn.csv",
        source_type=InformationSourceType.OFFICIAL,
        independence_group="ofac",
        domains=("legal_litigation_sanctions",),
        impact_channels=(PortfolioImpactChannel.REGULATION,),
        enabled=True,
        required=True,
        credential_environment_variables=(),
        user_agent_environment_variable=None,
        parameters={},
        headers={},
        maximum_records=10,
        reliability=0.99,
        relevance=0.9,
        materiality=0.8,
        license_identifier="ofac-public",
        usage_rights_identifier="official-analysis",
        limitations=("required",),
    )
    now = datetime(2026, 7, 28, 2, 0, tzinfo=timezone.utc)
    provider = ImpactfulPublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:test", (source,)),
        http_get=lambda *args, **kwargs: FakeResponse(),
        clock=lambda: now,
        sleeper=lambda _: None,
    )

    report = provider.collect()

    assert report.live_record_count == 1
    record = report.records[0]
    assert record.entities == ("Example Legacy Entity",)
    assert record.provenance.source_identifier == "12345"
    assert "TEST-PROGRAM" in record.tags
