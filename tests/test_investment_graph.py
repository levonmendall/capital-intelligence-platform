from datetime import UTC, datetime

import pytest

from data.investment_graph_store import InvestmentGraphIntegrityError, SQLiteInvestmentGraphStore
from intelligence.investment_graph import (
    InvestmentEntity,
    InvestmentEntityType,
    InvestmentRelationship,
    RelationshipConfidence,
    SemanticInvestmentGraph,
)


AS_OF = datetime(2026, 8, 3, tzinfo=UTC)


def _entity(identifier: str, entity_type: InvestmentEntityType) -> InvestmentEntity:
    return InvestmentEntity(identifier, entity_type, identifier, AS_OF, (f"source:{identifier}",))


def test_graph_finds_indirect_exposure_and_shared_dependency(tmp_path):
    entities = (
        _entity("holding:airline", InvestmentEntityType.HOLDING),
        _entity("holding:retailer", InvestmentEntityType.HOLDING),
        _entity("cost:fuel", InvestmentEntityType.COMMODITY),
        _entity("event:lower-oil", InvestmentEntityType.EVENT),
    )
    relationships = (
        InvestmentRelationship(
            "r1", "holding:airline", "depends_on", "cost:fuel",
            RelationshipConfidence.VERIFIED, 0.95, -1.0, AS_OF, AS_OF,
            ("filing:airline",), (),
        ),
        InvestmentRelationship(
            "r2", "holding:retailer", "depends_on", "cost:fuel",
            RelationshipConfidence.INFERRED, 0.70, -0.5, AS_OF, AS_OF,
            ("research:retailer",), ("Freight cost sensitivity is disproven.",),
        ),
        InvestmentRelationship(
            "r3", "event:lower-oil", "affects", "cost:fuel",
            RelationshipConfidence.VERIFIED, 0.90, -1.0, AS_OF, AS_OF,
            ("market:oil",), (),
        ),
    )
    graph = SemanticInvestmentGraph(entities, relationships)
    result = graph.query("holding:airline", "cost:fuel", as_of=AS_OF)
    assert result.exposure_known
    assert result.paths[0].cumulative_direction == -1.0
    assert graph.shared_dependencies(("holding:airline", "holding:retailer"), as_of=AS_OF) == {
        "cost:fuel": ("holding:airline", "holding:retailer")
    }

    unknown = graph.query("holding:airline", "missing", as_of=AS_OF)
    assert not unknown.exposure_known
    assert not unknown.zero_exposure_established

    store = SQLiteInvestmentGraphStore(tmp_path / "graph.sqlite")
    for item in entities:
        store.append_entity(item)
    for item in relationships:
        store.append_relationship(item)
    store.verify()
    with pytest.raises(InvestmentGraphIntegrityError):
        store._append("r1", "relationship", {"changed": True})
