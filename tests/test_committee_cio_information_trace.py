"""Behavioral tests for the audit-only committee and CIO information trace."""

from __future__ import annotations

from copy import deepcopy

from application import ProductionCanonicalCIOExecutor
from application.cio_cycle import CanonicalCIOCycle
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from evaluation.committee_cio_trace import (
    append_committee_cio_information_trace,
    build_committee_cio_information_trace,
)
from tests.test_canonical_cio_cycle import (
    _candidate,
    _construction_policy,
    _context,
    _opportunity_context,
    _portfolio,
)
from tests.test_canonical_production_context_adapter import (
    AS_OF as PRODUCTION_AS_OF,
    _adapter,
)


def _completed_trace(tmp_path, *, mutate_packet=None):
    candidate = _candidate("TRACE")
    portfolio = _portfolio((candidate,))
    context = _context(candidate)
    journal = SQLiteCIOJournal(tmp_path / "source.db")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
        journal=journal,
    ).run(
        identifier="cycle:committee-cio-trace",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(context,),
        portfolio=portfolio,
        code_version="commit:trace",
    )
    packet = journal.latest(
        aggregate_identifier=candidate.identifier,
        event_type=CIOJournalEventType.SPECIALIST_PACKET,
    )
    assert packet is not None
    payload = deepcopy(packet.payload)
    if mutate_packet is not None:
        mutate_packet(payload)
    trace = build_committee_cio_information_trace(
        candidate=candidate,
        context=context,
        portfolio=portfolio,
        packet_payload=payload,
        decision=result.decisions[0],
        snapshot=result.evaluation_snapshots[0],
        construction=result.construction,
        manifest=None,
        code_version="commit:trace",
    )
    return journal, result, trace


def test_trace_documents_all_six_specialists_and_cio_packet(tmp_path) -> None:
    _, result, trace = _completed_trace(tmp_path)
    payload = trace.to_dict()

    assert len(payload["specialists"]) == 6
    assert payload["committee_synthesis"]["exact_role_count"] == 6
    assert payload["normalized_point_in_time_record"]["fingerprint"] == (
        result.evaluation_snapshots[0].fingerprint
    )
    assert payload["cio_decision"]["action"] == result.decisions[0].action.value
    assert payload["initial_target"] == result.decisions[0].recommended_position_weight
    assert payload["authority"]["investment_behavior_changed"] is False
    assert all(
        item["direct_portfolio_action_authority"] is False
        for item in payload["specialists"]
    )


def test_trace_detects_correlated_directional_confirmation_not_discounted_everywhere(
    tmp_path,
) -> None:
    def correlate(payload):
        directional = [
            item
            for item in payload["analyses"]
            if item["role"]
            in {"macro_economic_strategist", "market_strategist"}
        ]
        for item in directional:
            item["position"] = "supportive"
            item["evidence_origin_identifiers"] = ["shared:origin"]

    _, _, trace = _completed_trace(tmp_path, mutate_packet=correlate)
    synthesis = trace.to_dict()["committee_synthesis"]

    assert synthesis["correlated_directional_clusters"]
    assert synthesis["return_reconciliation_dependency_discounted"] is True
    assert synthesis["growth_ensemble_and_support_ratios_dependency_discounted"] is False
    assert synthesis["correlated_opinions_partly_treated_as_independent"] is True


def test_information_go_no_go_exposes_missing_and_partial_cio_categories(
    tmp_path,
) -> None:
    _, _, trace = _completed_trace(tmp_path)
    payload = trace.to_dict()
    by_name = {
        item["name"]: item["status"]
        for item in payload["cio_information_sufficiency"]
    }

    assert by_name["expected return and horizon"] == "present_structured"
    assert by_name["benchmark-relative attractiveness"] == "missing"
    assert by_name["specialist agreement and disagreement"] == "partial"
    assert by_name["current exposures and available risk budget"] == "partial"
    assert payload["information_sufficiency_go_no_go"] == "no_go"


def test_trace_append_is_idempotent_and_hash_chained(tmp_path) -> None:
    _, _, trace = _completed_trace(tmp_path)
    destination = SQLiteCIOJournal(tmp_path / "trace.db")

    first = append_committee_cio_information_trace(destination, trace)
    second = append_committee_cio_information_trace(destination, trace)

    assert first.content_hash == second.content_hash
    assert destination.count() == 1
    assert destination.verify_integrity()


def test_active_executor_appends_trace_for_each_cio_decision(tmp_path) -> None:
    _, screening_store, adapter = _adapter(tmp_path)
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(journal=journal),
        screening_store=screening_store,
        context_provider=adapter,
    )

    result = executor.run(as_of=PRODUCTION_AS_OF)
    traces = journal.events(
        event_type=CIOJournalEventType.COMMITTEE_CIO_INFORMATION_TRACE,
    )

    assert len(traces) == len(result.decisions)
    assert traces[0].payload["normalized_point_in_time_record"]["fingerprint"]
    assert journal.verify_integrity()


def test_trace_failure_cannot_change_cio_result(tmp_path, monkeypatch) -> None:
    _, screening_store, adapter = _adapter(tmp_path)
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(journal=journal),
        screening_store=screening_store,
        context_provider=adapter,
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("trace store unavailable")

    monkeypatch.setattr(
        "evaluation.committee_cio_trace.append_committee_cio_information_trace",
        fail,
    )
    result = executor.run(as_of=PRODUCTION_AS_OF)

    assert result.decisions
    assert not journal.events(
        event_type=CIOJournalEventType.COMMITTEE_CIO_INFORMATION_TRACE,
    )
    assert journal.verify_integrity()
