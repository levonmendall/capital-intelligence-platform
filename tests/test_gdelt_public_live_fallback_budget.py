from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest
import requests

from data.decision_information import InformationSourceType, PortfolioImpactChannel
from operations import public_live_requirement_qualification as qualification
from providers import public_live_information as public_provider
from providers.public_live_information import (
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
)
from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider as BaseImpactfulPublicLiveInformationProvider,
)


NOW = datetime(2026, 8, 27, 21, 0, tzinfo=timezone.utc)
GROUP = "gdelt-global-news-discovery"


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _gdelt_source(identifier: str, endpoint: str) -> PublicLiveSourceDefinition:
    return PublicLiveSourceDefinition(
        identifier=identifier,
        source_name=identifier,
        parser="gdelt_doc",
        endpoint=endpoint,
        source_type=InformationSourceType.ALTERNATIVE,
        independence_group="gdelt-news-discovery",
        domains=("current_events_news",),
        impact_channels=(
            PortfolioImpactChannel.GROWTH,
            PortfolioImpactChannel.VOLATILITY,
        ),
        enabled=True,
        required=True,
        credential_environment_variables=(),
        user_agent_environment_variable=None,
        parameters={},
        headers={},
        maximum_records=10,
        reliability=0.55,
        relevance=0.7,
        materiality=0.45,
        license_identifier="GDELT-public-api-metadata",
        usage_rights_identifier="metadata-only",
        limitations=("required", "metadata only"),
        requirement_group=GROUP,
    )


def _catalog() -> tuple[
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
    PublicLiveSourceDefinition,
]:
    primary = _gdelt_source(
        "gdelt-global-news-discovery",
        "https://api.gdeltproject.org/api/v2/doc/doc",
    )
    fallback = _gdelt_source(
        "gdelt-global-context-discovery",
        "https://api.gdeltproject.org/api/v2/context/context",
    )
    return PublicLiveSourceCatalog("catalog:gdelt", (primary, fallback)), primary, fallback


def test_gdelt_request_policy_reserves_fallback_and_completion_budget() -> None:
    policy = qualification._gdelt_provider_request_policy(
        requirement_group=GROUP,
        provider_count=2,
        values={},
    )

    assert policy is not None
    request_timeout, attempts = policy
    assert attempts == 2
    assert request_timeout == pytest.approx(14.875)

    worst_case_network_seconds = (
        2 * attempts * request_timeout
        + 2 * qualification._PROVIDER_RETRY_BASE_DELAY_SECONDS
    )
    assert worst_case_network_seconds == pytest.approx(60.0)
    assert (
        qualification._DEFAULT_REQUIREMENT_TIMEOUT_SECONDS
        - worst_case_network_seconds
    ) == pytest.approx(15.0)


def test_gdelt_request_policy_scales_with_existing_outer_timeout() -> None:
    policy = qualification._gdelt_provider_request_policy(
        requirement_group=GROUP,
        provider_count=2,
        values={
            "CAPITAL_INTELLIGENCE_EVIDENCE_PUBLIC_REQUIREMENT_TIMEOUT_SECONDS": "33"
        },
    )

    assert policy is not None
    request_timeout, attempts = policy
    worst_case_network_seconds = (
        2 * attempts * request_timeout
        + 2 * qualification._PROVIDER_RETRY_BASE_DELAY_SECONDS
    )
    assert attempts == 2
    assert worst_case_network_seconds == pytest.approx(33.0 * 0.80)


def test_non_gdelt_requirement_keeps_established_provider_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = replace(
        _gdelt_source(
            "other-primary",
            "https://example.test/other",
        ),
        requirement_group="other-required-information",
    )
    scoped = PublicLiveSourceCatalog("catalog:other", (source,))
    observed: list[dict[str, object]] = []

    class Provider:
        def __init__(self, _catalog, **kwargs) -> None:
            observed.append(dict(kwargs))

    monkeypatch.setattr(
        qualification,
        "ImpactfulPublicLiveInformationProvider",
        Provider,
    )

    qualification._requirement_provider(
        scoped_catalog=scoped,
        requirement_group="other-required-information",
        values={},
    )

    assert observed == [{}]


def test_slow_gdelt_primary_cannot_starve_context_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    catalog, primary, fallback = _catalog()
    calls: list[tuple[str, float]] = []
    provider_kwargs: list[dict[str, object]] = []

    payload = {
        "articles": [
            {
                "title": "Global market development",
                "url": "https://publisher.example/global-market-development",
                "domain": "publisher.example",
                "seendate": "20260827T205500Z",
            }
        ]
    }

    def get(endpoint: str, **kwargs):
        calls.append((endpoint, float(kwargs["timeout"])))
        if endpoint == primary.endpoint:
            raise requests.Timeout("primary request exhausted its bounded slice")
        assert endpoint == fallback.endpoint
        return FakeResponse(payload)

    class Provider(BaseImpactfulPublicLiveInformationProvider):
        def __init__(self, scoped_catalog, **kwargs) -> None:
            provider_kwargs.append(dict(kwargs))
            super().__init__(
                scoped_catalog,
                http_get=get,
                clock=lambda: NOW,
                sleeper=lambda _seconds: None,
                **kwargs,
            )

    monkeypatch.setattr(qualification, "_catalog", lambda _values: catalog)
    monkeypatch.setattr(
        qualification,
        "ImpactfulPublicLiveInformationProvider",
        Provider,
    )
    monkeypatch.setattr(
        public_provider,
        "collect_finra_fixed_income_context",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        qualification,
        "_write_rolling_records",
        lambda **_kwargs: 1,
    )

    result = qualification.collect_required_public_live_requirement(
        requirement_group=GROUP,
        as_of=NOW,
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
    )

    assert provider_kwargs == [
        {
            "timeout": pytest.approx(14.875),
            "max_attempts": 2,
        }
    ]
    assert [endpoint for endpoint, _timeout in calls] == [
        primary.endpoint,
        primary.endpoint,
        fallback.endpoint,
    ]
    assert all(timeout == pytest.approx(14.875) for _endpoint, timeout in calls)
    assert result["provider"] == fallback.identifier
    assert result["fallback_providers_attempted"] == [primary.identifier]


def test_gdelt_still_fails_closed_after_both_members_exhaust_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    catalog, primary, fallback = _catalog()
    calls: list[str] = []

    def get(endpoint: str, **_kwargs):
        calls.append(endpoint)
        raise requests.Timeout("provider unavailable")

    class Provider(BaseImpactfulPublicLiveInformationProvider):
        def __init__(self, scoped_catalog, **kwargs) -> None:
            super().__init__(
                scoped_catalog,
                http_get=get,
                clock=lambda: NOW,
                sleeper=lambda _seconds: None,
                **kwargs,
            )

    monkeypatch.setattr(qualification, "_catalog", lambda _values: catalog)
    monkeypatch.setattr(
        qualification,
        "ImpactfulPublicLiveInformationProvider",
        Provider,
    )
    monkeypatch.setattr(
        public_provider,
        "collect_finra_fixed_income_context",
        lambda **_kwargs: None,
    )

    with pytest.raises(
        qualification._plane.ContinuousEvidencePlaneError,
        match="required public live information is not qualified",
    ) as captured:
        qualification.collect_required_public_live_requirement(
            requirement_group=GROUP,
            as_of=NOW,
            values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        )

    assert calls == [
        primary.endpoint,
        primary.endpoint,
        fallback.endpoint,
        fallback.endpoint,
    ]
    detail = str(captured.value)
    assert f"provider={primary.identifier}" in detail
    assert f"fallback_providers_attempted={fallback.identifier}" in detail
