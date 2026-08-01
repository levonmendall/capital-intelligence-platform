from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tests/test_production_context_assembly.py"
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    "from portfolio.state import (\n",
    "from opportunity.snapshot import (\n"
    "    PUBLICATION_SNAPSHOT_KIND,\n"
    "    build_opportunity_snapshot,\n"
    ")\n"
    "from portfolio.state import (\n",
    "snapshot imports",
)
replace_once(
    '''    queue = OpportunityEngine().build_queue(
        (candidate,),
        _screening_context(),
    )
    publication = FullUniverseScreeningPublication(
        identifier="publication:screening:production",
''',
    '''    engine = OpportunityEngine()
    context = _screening_context()
    queue = engine.build_queue(
        (candidate,),
        context,
    )
    publication_identifier = "publication:screening:production"
    snapshot_payload = build_opportunity_snapshot(
        snapshot_kind=PUBLICATION_SNAPSHOT_KIND,
        context=context,
        queue=queue,
        engine=engine,
        created_at=AS_OF,
        code_version="commit:integration",
        screening_publication_identifier=publication_identifier,
    )
    publication = FullUniverseScreeningPublication(
        identifier=publication_identifier,
''',
    "snapshot fixture construction",
)
replace_once(
    '''        opportunity_queue_payload=serialize_opportunity_queue(
            queue,
            occurred_at=AS_OF,
        ),
''',
    '''        opportunity_queue_payload={
            **serialize_opportunity_queue(
                queue,
                occurred_at=AS_OF,
            ),
            "opportunity_context_snapshot": snapshot_payload,
        },
''',
    "snapshot fixture persistence",
)
replace_once(
    '''        CIOJournalEventType.OPPORTUNITY_QUEUE,
        CIOJournalEventType.SPECIALIST_PACKET,
''',
    '''        CIOJournalEventType.OPPORTUNITY_QUEUE,
        CIOJournalEventType.OPPORTUNITY_DECISION_SNAPSHOT,
        CIOJournalEventType.SPECIALIST_PACKET,
''',
    "decision snapshot event assertion",
)
path.write_text(text, encoding="utf-8")
