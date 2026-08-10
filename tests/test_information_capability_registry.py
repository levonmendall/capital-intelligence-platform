from governance.information_capability_registry import (
    CoverageScope,
    InformationCapabilityRecord,
    InformationCapabilityRegistry,
)


def test_registry_distinguishes_monitored_certified_and_allocatable() -> None:
    monitored = InformationCapabilityRecord(
        identifier="monitor",
        domains=("positioning",),
        implemented=True,
        configured=True,
        reachable=True,
        healthy=True,
    )
    certified = InformationCapabilityRecord(
        identifier="certified",
        domains=("macro",),
        implemented=True,
        configured=True,
        credentialed=True,
        reachable=True,
        collecting=True,
        point_in_time_capable=True,
        historical_capable=True,
        decision_certified=True,
        healthy=True,
    )
    registry = InformationCapabilityRegistry((monitored, certified))
    assert registry.coverage("positioning", required_scope=CoverageScope.MONITORED)
    assert not registry.coverage("positioning")
    assert registry.coverage("macro")
    gaps = registry.gaps(("positioning", "macro"))
    assert tuple(item.domain for item in gaps) == ("positioning",)
    assert "complete decision-evidence certification" in gaps[0].remediation


def test_allocatable_cannot_exist_without_decision_certification() -> None:
    try:
        InformationCapabilityRecord(
            identifier="bad",
            domains=("market_prices",),
            implemented=True,
            allocatable=True,
        )
    except ValueError as error:
        assert "decision certified" in str(error)
    else:
        raise AssertionError("allocatable must imply decision certification")
