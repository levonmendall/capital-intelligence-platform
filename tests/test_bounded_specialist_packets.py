from __future__ import annotations

from types import SimpleNamespace

from application.bounded_cio_cycle import (
    BoundedCanonicalCIOCycle,
    BoundedCompoundingCanonicalCIOCycle,
)
from application.bounded_specialist_packets import (
    JournalBackedSpecialistPacketLoader,
    RecomputingSpecialistPacketSource,
    deserialize_specialist_packet,
)
from application.cio_cycle import CanonicalCIOCycle
from application.compounding_cycle import CompoundingCanonicalCIOCycle
from application.global_rotation_preliminary import PrecomputedSpecialistService
from cio import IndependentSpecialistPacket
from cio.persistence import SQLiteCIOJournal, serialize_specialist_packet
from tests.cio_test_fixtures import build_candidate, build_specialist_packet


def _packet() -> IndependentSpecialistPacket:
    candidate = build_candidate()
    return build_specialist_packet(candidate)


def test_specialist_packet_journal_payload_round_trips_exactly() -> None:
    packet = _packet()
    serialized = serialize_specialist_packet(packet, code_version="test")

    restored = deserialize_specialist_packet(serialized)

    assert restored == packet


def test_journal_loader_reads_only_the_current_cycle_packet(tmp_path) -> None:
    packet = _packet()
    journal = SQLiteCIOJournal(tmp_path / "cio.sqlite3")
    event = journal.append_specialist_packet(
        packet,
        occurred_at=max(item.completed_at for item in packet.analyses),
        code_version="test",
    )
    loader = JournalBackedSpecialistPacketLoader(
        journal,
        {packet.candidate_identifier: event.event_identifier},
    )

    assert loader.load(packet.candidate_identifier) == packet


def test_recomputing_source_never_caches_full_packets() -> None:
    packet = _packet()
    calls: list[str] = []

    def load(candidate_identifier: str) -> IndependentSpecialistPacket:
        calls.append(candidate_identifier)
        return packet

    source = RecomputingSpecialistPacketSource(
        (packet.candidate_identifier,),
        load,
    )

    assert source.get(packet.candidate_identifier) is packet
    assert source.get(packet.candidate_identifier) is packet
    assert calls == [packet.candidate_identifier, packet.candidate_identifier]
    assert source.get("candidate:UNKNOWN") is None


def test_precomputed_service_accepts_non_mapping_packet_source() -> None:
    candidate = build_candidate()
    packet = build_specialist_packet(candidate)
    delegate_calls: list[str] = []

    class Delegate:
        def analyze(self, candidate, context):
            delegate_calls.append(candidate.identifier)
            return packet

    class Source:
        def get(self, candidate_identifier: str):
            assert candidate_identifier == packet.candidate_identifier
            return packet

    service = PrecomputedSpecialistService(Delegate())
    context = SimpleNamespace(historical_learning=packet.historical_learning)

    with service.bind_packets(Source()):
        assert service.analyze(candidate, context) is packet

    assert delegate_calls == []


def test_compounding_mro_routes_through_bounded_canonical_cycle() -> None:
    mro = BoundedCompoundingCanonicalCIOCycle.mro()

    assert mro.index(CompoundingCanonicalCIOCycle) < mro.index(BoundedCanonicalCIOCycle)
    assert mro.index(BoundedCanonicalCIOCycle) < mro.index(CanonicalCIOCycle)
