
def test_specialist_and_decision_serializers_preserve_authority_and_dissent() -> None:
    candidate = build_candidate()
    packet = build_specialist_packet(candidate)
    decision = build_decision(candidate)

    packet_payload = serialize_specialist_packet(
        packet,
        code_version="commit-1",
    )
    decision_payload = serialize_cio_decision(
        decision,
        code_version="commit-1",
    )

    assert len(packet_payload["analyses"]) == 6
    assert all(
        item["independent_first_pass"]
        for item in packet_payload["analyses"]
    )
    portfolio_analysis = next(
        item
        for item in packet_payload["analyses"]
        if item["role"] == "portfolio_risk_manager"
    )
    assert portfolio_analysis["recommended_position_weight"] == pytest.approx(
        0.06
    )
    assert decision_payload["action"] == "buy"
    assert decision_payload["recommended_position_weight"] == pytest.approx(
        0.06
    )
    assert (
        decision_payload["policy_version"]
        == "cio-synthesis.v9-independent-evidence"
    )


def test_event_payload_is_canonical_json(tmp_path) -> None:
    journal = _journal(tmp_path)
    event = journal.append(
        event_type=CIOJournalEventType.CANDIDATE_DECISION,
        aggregate_identifier="candidate:test",
        occurred_at=AS_OF,
        payload={"z": 1, "a": {"y": 2, "x": 1}},
        schema_version="test.v1",