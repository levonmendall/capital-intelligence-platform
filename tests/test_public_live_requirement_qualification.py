from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from operations import public_live_requirement_qualification as qualification
from operations.evidence_prequalification_attribution import (
    failed_prequalification_attribution,
)


def _source(identifier: str, group: str, *, required: bool = True):
    return SimpleNamespace(
        identifier=identifier,
        parser="test",
        endpoint=f"https://example.com/{identifier}",
        enabled=True,
        required=required,
        requirement_group=group,
        credential_environment_variables=(),
        parameters={},
        headers={},
        maximum_records=10,
    )


def test_required_groups_preserve_catalog_order(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = SimpleNamespace(
        identifier="catalog",
        sources=(
            _source("alpha-primary", "macro-rates"),
            _source("alpha-fallback", "macro-rates"),
            _source("beta", "policy-events"),
            _source("optional", "", required=False),
        ),
    )
    monkeypatch.setattr(qualification, "_catalog", lambda _values: catalog)

    assert qualification.required_public_live_requirement_groups({}) == (
        "macro-rates",
        "policy-events",
    )


def test_failed_group_preserves_requirement_and_fallback_attribution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    catalog = SimpleNamespace(
        identifier="catalog",
        sources=(
            _source("fred", "macro-rates"),
            _source("oecd", "macro-rates"),
        ),
    )
    report = SimpleNamespace(
        catalog_identifier="catalog",
        evaluated_at=now,
        required_sources_ready=False,
        records=(),
        sources=(
            SimpleNamespace(
                source_identifier="fred",
                requirement_group="macro-rates",
                succeeded=False,
            ),
            SimpleNamespace(
                source_identifier="oecd",
                requirement_group="macro-rates",
                succeeded=False,
            ),
        ),
    )

    class Provider:
        def __init__(self, scoped_catalog) -> None:
            assert len(scoped_catalog.sources) == 2

        def collect(self, *, include_optional: bool):
            assert include_optional is False
            return report

    monkeypatch.setattr(qualification, "_catalog", lambda _values: catalog)
    monkeypatch.setattr(qualification, "ImpactfulPublicLiveInformationProvider", Provider)

    with pytest.raises(Exception) as captured:
        qualification.collect_required_public_live_requirement(
            requirement_group="macro-rates",
            as_of=now,
            values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        )

    detail = str(captured.value)
    assert "required_information=macro-rates" in detail
    assert "provider=fred" in detail
    assert "fallback_providers_attempted=oecd" in detail

    attribution = failed_prequalification_attribution(detail=detail).as_dict()
    assert attribution["capability"] == "public_live_information"
    assert attribution["required_information"] == "macro-rates"
    assert attribution["provider"] == "fred"
    assert attribution["fallback_providers_attempted"] == ["oecd"]


def test_maintainer_reuses_qualified_group_and_acquires_only_missing_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    records_path = tmp_path / "public-live-information-records.json"
    records_path.write_text('{"records": [], "coverage": {}}\n', encoding="utf-8")
    catalog = SimpleNamespace(
        identifier="catalog",
        sources=(
            _source("alpha", "macro-rates"),
            _source("beta", "policy-events"),
        ),
    )
    cached = SimpleNamespace(
        component_id="component-macro",
        payload={
            "provider": "alpha",
            "fallback_providers_attempted": [],
        },
    )
    acquired: list[str] = []
    finalized: list[tuple[str, ...]] = []

    monkeypatch.setattr(qualification, "_catalog", lambda _values: catalog)
    monkeypatch.setattr(
        qualification,
        "required_public_live_requirement_groups",
        lambda _values: ("macro-rates", "policy-events"),
    )
    monkeypatch.setattr(qualification, "_records_path", lambda _values: records_path)
    monkeypatch.setattr(
        qualification,
        "_component_compatibility",
        lambda _catalog, group: f"compatibility:{group}",
    )

    def load_component(*, component_name: str, **_kwargs):
        if component_name.endswith("macro-rates"):
            return cached
        return None

    monkeypatch.setattr(qualification._ledger, "load_qualified_component", load_component)

    def acquire(*, requirement_group: str, **_kwargs):
        acquired.append(requirement_group)
        return {
            "qualified": True,
            "component_id": "component-policy",
            "provider": "beta",
            "fallback_providers_attempted": [],
        }

    monkeypatch.setattr(
        qualification,
        "_qualify_and_checkpoint_requirement",
        acquire,
    )
    monkeypatch.setattr(
        qualification,
        "finalize_required_public_live_requirements",
        lambda *, requirement_groups, **_kwargs: finalized.append(requirement_groups),
    )

    result = qualification.maintain_required_public_live_requirements(
        as_of=now,
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
    )

    assert acquired == ["policy-events"]
    assert finalized == [("macro-rates", "policy-events")]
    assert result.required_sources_ready is True
    assert result.qualified_requirement_reused_count == 1
    assert result.qualified_requirement_component_ids == (
        "component-macro",
        "component-policy",
    )


def test_maintainer_checkpoints_later_groups_before_aggregate_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    catalog = SimpleNamespace(
        identifier="catalog",
        sources=(
            _source("alpha", "macro-rates"),
            _source("beta", "policy-events"),
        ),
    )
    attempted: list[str] = []

    monkeypatch.setattr(qualification, "_catalog", lambda _values: catalog)
    monkeypatch.setattr(
        qualification,
        "required_public_live_requirement_groups",
        lambda _values: ("macro-rates", "policy-events"),
    )
    monkeypatch.setattr(
        qualification,
        "_component_compatibility",
        lambda _catalog, group: f"compatibility:{group}",
    )
    monkeypatch.setattr(
        qualification._ledger,
        "load_qualified_component",
        lambda **_kwargs: None,
    )

    def acquire(*, requirement_group: str, **_kwargs):
        attempted.append(requirement_group)
        if requirement_group == "macro-rates":
            raise qualification._plane.ContinuousEvidencePlaneError(
                "required public live information is not qualified; "
                "required_information=macro-rates; provider=fred; "
                "fallback_providers_attempted=oecd"
            )
        return {
            "qualified": True,
            "component_id": "component-policy",
            "provider": "beta",
            "fallback_providers_attempted": [],
        }

    monkeypatch.setattr(
        qualification,
        "_qualify_and_checkpoint_requirement",
        acquire,
    )

    with pytest.raises(
        qualification._plane.ContinuousEvidencePlaneError,
        match="failed_required_information=macro-rates",
    ):
        qualification.maintain_required_public_live_requirements(
            as_of=now,
            values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        )

    assert attempted == ["macro-rates", "policy-events"]


def test_stale_checkpoint_is_not_reused(
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    component_name = qualification._component_name("macro-rates")
    compatibility = "compatibility"
    qualification._ledger.publish_qualified_component(
        values=values,
        component_name=component_name,
        compatibility=compatibility,
        as_of=now - timedelta(hours=1),
        completed_at=now - timedelta(hours=1),
        max_age_seconds=60,
        payload={"provider": "fred", "fallback_providers_attempted": []},
    )

    assert qualification._ledger.load_qualified_component(
        values=values,
        component_name=component_name,
        compatibility=compatibility,
        cutoff=now,
    ) is None
