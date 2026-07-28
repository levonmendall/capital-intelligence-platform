from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from data.decision_information import InformationSourceType, PortfolioImpactChannel
from providers.public_live_information import (
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
)
from providers.public_live_information_runtime import (
    GovernedPublicLiveInformationProvider,
)


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_future_weather_onset_is_preserved_without_rejecting_record() -> None:
    source = PublicLiveSourceDefinition(
        identifier="nws:test",
        source_name="NWS Test",
        parser="nws_alerts",
        endpoint="https://api.weather.gov/alerts/active",
        source_type=InformationSourceType.OFFICIAL,
        independence_group="nws",
        domains=("weather_climate_disasters",),
        impact_channels=(PortfolioImpactChannel.CLIMATE_WEATHER,),
        enabled=True,
        required=True,
        credential_environment_variables=(),
        user_agent_environment_variable=None,
        parameters={},
        headers={},
        maximum_records=10,
        reliability=0.99,
        relevance=0.8,
        materiality=0.7,
        license_identifier="nws-public",
        usage_rights_identifier="official-analysis",
        limitations=("required",),
    )
    payload = {
        "features": [
            {
                "id": "alert-1",
                "properties": {
                    "id": "alert-1",
                    "event": "Winter Storm Watch",
                    "headline": "Winter Storm Watch issued",
                    "description": "Heavy snow is possible.",
                    "sent": "2026-07-28T01:00:00+00:00",
                    "onset": "2026-07-28T06:00:00+00:00",
                    "areaDesc": "Test Region",
                    "severity": "Severe",
                    "urgency": "Future",
                },
            }
        ]
    }
    now = datetime(2026, 7, 28, 1, 1, tzinfo=timezone.utc)
    provider = GovernedPublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:test", (source,)),
        http_get=lambda *args, **kwargs: FakeResponse(payload),
        clock=lambda: now,
        sleeper=lambda _: None,
    )

    report = provider.collect()

    assert report.live_record_count == 1
    record = report.records[0]
    assert record.event_at == record.published_at
    assert "scheduled-event" in record.tags
    assert "scheduled-event-at:2026-07-28T06:00:00+00:00" in record.tags
