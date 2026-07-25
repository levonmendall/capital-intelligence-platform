"""Tests for investor memory, conviction trends, and opportunity cost."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from personalization import (
    InvestorBehaviorTag,
    InvestorDecisionAction,
    InvestorMemoryEvent,
    InvestorMemoryEventType,
    InvestorRiskLevel,
    SQLiteInvestorMemoryStore,
    investor_memory_profile_to_dict,
)
from portfolio import (
    AssetBucket,
    AssetBucketLimit,
    FundingCandidate,
    PortfolioMandate,
    PortfolioPosition,
    PortfolioProposal,
    PortfolioSnapshot,
    assess_opportunity_cost,
    opportunity_cost_to_dict,
)
from reporting import (
    ConvictionDirection,
    build_conviction_trend,
    build_conviction_trend_from_store,
    conviction_trend_to_dict,
)


FIRST = datetime(2026, 1, 27, 12, tzinfo=timezone.utc)
SECOND = FIRST + timedelta(days=1)
THIRD = SECOND + timedelta(days=1)


def _memory_event(
    identifier: str,
    when: datetime,
    *,
    event_type: InvestorMemoryEventType,
    action: InvestorDecisionAction | None = None,
    risk: InvestorRiskLevel | None = None,
    tags: tuple[InvestorBehaviorTag, ...] = (),
    lesson: str | None = None,
) -> InvestorMemoryEvent:
    return InvestorMemoryEvent(
        identifier=identifier,
        investor_identifier="primary",
        recorded_at=when,
        event_type=event_type,
        summary=lesson or identifier,
        source_decision_identifier="decision:1",
        action=action,
        risk_level=risk,
        behavior_tags=tags,
        lesson=lesson,
    )


def test_investor_memory_remembers_explicit_preferences_and_recurring_mistakes(
    tmp_path,
) -> None:
    store = SQLiteInvestorMemoryStore(tmp_path / "memory.db")
    store.append(
        _memory_event(
            "risk:1",
            FIRST,
            event_type=InvestorMemoryEventType.RISK_PREFERENCE,
            risk=InvestorRiskLevel.LOW,
        )
    )
    store.append(
        _memory_event(
            "risk:2",
            SECOND,
            event_type=InvestorMemoryEventType.RISK_PREFERENCE,
            risk=InvestorRiskLevel.MODERATE,
        )
    )
    for index, when in enumerate((SECOND, THIRD), start=1):
        store.append(
            _memory_event(
                f"mistake:{index}",
                when,
                event_type=InvestorMemoryEventType.MISTAKE,
                action=InvestorDecisionAction.DELAYED,
                tags=(InvestorBehaviorTag.DELAYED_ACTION,),
                lesson="Decide from the process, not from the latest headline.",
            )
        )

    profile = store.profile("primary")
    payload = investor_memory_profile_to_dict(profile)

    assert profile.preferred_risk_level is InvestorRiskLevel.MODERATE
    assert profile.recurring_mistakes[0].code == "delayed_action"
    assert profile.recurring_mistakes[0].count == 2
    assert profile.lessons == (
        "Decide from the process, not from the latest headline.",
    )
    assert payload["memory_is_explicit"] is True
    assert payload["schema_version"] == "investor-memory.v1"


def test_investor_memory_is_append_only_and_read_only_safe(tmp_path) -> None:
    store = SQLiteInvestorMemoryStore(tmp_path / "memory.db")
    event = _memory_event(
        "action:1",
        FIRST,
        event_type=InvestorMemoryEventType.DECISION_ACTION,
        action=InvestorDecisionAction.FOLLOWED,
        tags=(InvestorBehaviorTag.FOLLOWED_PROCESS,),
    )
    store.append(event)
    store.append(event)
    assert store.count("primary") == 1

    connection = sqlite3.connect(store.path)
    try:
        try:
            connection.execute(
                "UPDATE investor_memory_events SET event_type = 'lesson'"
            )
        except sqlite3.IntegrityError as error:
            assert "append-only" in str(error)
        else:
            raise AssertionError("investor memory allowed an update")
    finally:
        connection.close()

    reader = SQLiteInvestorMemoryStore(store.path, read_only=True)
    assert reader.profile("primary").total_events == 1
    try:
        reader.append(event)
    except PermissionError:
        pass
    else:
        raise AssertionError("read-only investor memory allowed append")


def _daily_payload(
    as_of: datetime,
    *,
    score: int,
    evidence: float,
    support: float,
    agreement: float,
) -> dict[str, object]:
    return {
        "schema_version": "daily-capital-intelligence.v1",
        "identifier": f"daily:{as_of.isoformat()}",
        "as_of": as_of.isoformat(),
        "generated_at": as_of.isoformat(),
        "status": "current",
        "score": {
            "score": score,
            "components": {
                "evidence_confidence": evidence,
                "committee_support": support,
                "committee_agreement": agreement,
            },
        },
    }


def test_conviction_trend_shows_direction_and_drivers() -> None:
    payloads = (
        _daily_payload(
            FIRST,
            score=74,
            evidence=0.70,
            support=0.70,
            agreement=0.70,
        ),
        _daily_payload(
            SECOND,
            score=78,
            evidence=0.76,
            support=0.80,
            agreement=0.78,
        ),
        _daily_payload(
            THIRD,
            score=82,
            evidence=0.84,
            support=0.90,
            agreement=0.84,
        ),
    )

    trend = build_conviction_trend(payloads, lookback=7)
    result = conviction_trend_to_dict(trend)

    assert trend.direction is ConvictionDirection.RISING
    assert trend.current > trend.previous
    assert trend.change_points >= 2
    assert trend.score_change_points == 4
    assert trend.streak == 2
    assert trend.drivers[0].component in {
        "evidence confidence",
        "committee support",
    }
    assert result["schema_version"] == "conviction-trend.v1"
    assert len(result["history"]) == 3


def test_conviction_trend_reads_append_only_daily_payloads(tmp_path) -> None:
    database = tmp_path / "daily.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE daily_intelligence_snapshots (
                identifier TEXT PRIMARY KEY,
                as_of TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL
            )
            """
        )
        for payload in (
            _daily_payload(
                FIRST,
                score=70,
                evidence=0.65,
                support=0.70,
                agreement=0.65,
            ),
            _daily_payload(
                SECOND,
                score=75,
                evidence=0.75,
                support=0.75,
                agreement=0.75,
            ),
        ):
            connection.execute(
                """
                INSERT INTO daily_intelligence_snapshots (
                    identifier, as_of, payload_json
                ) VALUES (?, ?, ?)
                """,
                (
                    payload["identifier"],
                    payload["as_of"],
                    json.dumps(payload),
                ),
            )

    trend = build_conviction_trend_from_store(database, lookback=7)
    assert trend.direction is ConvictionDirection.RISING
    assert trend.capital_intelligence_score == 75


def _portfolio_context():
    snapshot = PortfolioSnapshot(
        identifier="portfolio:1",
        as_of=FIRST,
        nav=100_000,
        cash_weight=0.10,
        risk_budget_used=0.50,
        positions=(
            PortfolioPosition(
                identifier="SPY",
                bucket=AssetBucket.EQUITY,
                weight=0.50,
                risk_budget_usage=0.30,
                liquidity_score=1.0,
                exposure_tags=("us-equity", "risk-assets"),
            ),
            PortfolioPosition(
                identifier="BND",
                bucket=AssetBucket.FIXED_INCOME,
                weight=0.40,
                risk_budget_usage=0.20,
                liquidity_score=1.0,
                exposure_tags=("duration",),
            ),
        ),
    )
    mandate = PortfolioMandate(
        identifier="mandate:1",
        version="v1",
        maximum_position_weight=0.60,
        minimum_cash_weight=0.05,
        maximum_risk_budget=0.80,
        minimum_liquidity_score=0.50,
        bucket_limits=(
            AssetBucketLimit(AssetBucket.EQUITY, 0.70),
        ),
    )
    proposal = PortfolioProposal(
        identifier="proposal:1",
        source_decision_identifier="decision:1",
        target_identifier="EM-EQUITY",
        bucket=AssetBucket.EQUITY,
        requested_weight_delta=0.08,
        estimated_risk_budget_delta=0.05,
        liquidity_score=0.90,
        exposure_tags=("risk-assets", "emerging-markets"),
    )
    return snapshot, mandate, proposal


def test_opportunity_cost_explains_funding_sources_and_tradeoffs() -> None:
    snapshot, mandate, proposal = _portfolio_context()
    candidate = FundingCandidate(
        position_identifier="SPY",
        maximum_reduction=0.03,
        priority=1,
        reason="reduce overlapping broad equity exposure",
        trade_off="The portfolio may forgo upside from United States equities.",
    )

    assessment = assess_opportunity_cost(
        snapshot,
        mandate,
        proposal,
        funding_candidates=(candidate,),
    )
    payload = opportunity_cost_to_dict(assessment)

    assert assessment.fully_funded
    assert assessment.funded_weight == 0.08
    assert assessment.cash_weight_after == 0.05
    assert [source.identifier for source in assessment.funding_sources] == [
        "cash-above-reserve",
        "SPY",
    ]
    assert payload["schema_version"] == "opportunity-cost.v1"
    assert payload["non_executing"] is True
    assert len(payload["trade_offs"]) >= 2


def test_opportunity_cost_never_chooses_a_sale_silently() -> None:
    snapshot, mandate, proposal = _portfolio_context()

    assessment = assess_opportunity_cost(snapshot, mandate, proposal)

    assert not assessment.fully_funded
    assert assessment.funded_weight == 0.05
    assert assessment.funding_gap == 0.03
    assert assessment.alternative_sources == ("SPY",)
    assert "will not choose a sale silently" in assessment.summary
