from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tests/test_canonical_production_context_adapter.py"
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    "from opportunity import OpportunityEngine\n",
    "from opportunity import OpportunityEngine\n"
    "from opportunity.snapshot import (\n"
    "    PUBLICATION_SNAPSHOT_KIND,\n"
    "    build_opportunity_snapshot,\n"
    ")\n",
    "snapshot imports",
)
replace_once(
    '''    queue = OpportunityEngine().build_queue(
        (candidate,),
        _screening_context(),
    )
    queue_payload = serialize_opportunity_queue(
        queue,
        occurred_at=AS_OF,
    )
''',
    '''    engine = OpportunityEngine()
    context = _screening_context()
    queue = engine.build_queue(
        (candidate,),
        context,
    )
    publication_identifier = "publication:screening:canonical-adapter"
    snapshot_payload = build_opportunity_snapshot(
        snapshot_kind=PUBLICATION_SNAPSHOT_KIND,
        context=context,
        queue=queue,
        engine=engine,
        created_at=AS_OF,
        code_version="commit:canonical-adapter",
        screening_publication_identifier=publication_identifier,
    )
    queue_payload = {
        **serialize_opportunity_queue(
            queue,
            occurred_at=AS_OF,
        ),
        "opportunity_context_snapshot": snapshot_payload,
    }
''',
    "fixture snapshot construction",
)
replace_once(
    '''            "rejected": [
                {
                    "candidate_identifier": candidate.identifier,
                    "outcome": "rejected",
                    "universe_disposition": "direct_recommendation",
                    "universe_policy_version": "recommendation-universe.v1",
                    "effective_opportunity_cost": 0.04,
                    "opportunity_edge": candidate.opportunity_edge,
                    "reasons": ["forced persisted rejection for drift test"],
                }
            ],
        }
''',
    '''            "rejected": [
                {
                    "candidate_identifier": candidate.identifier,
                    "outcome": "rejected",
                    "universe_disposition": "direct_recommendation",
                    "universe_policy_version": "recommendation-universe.v1",
                    "effective_opportunity_cost": 0.04,
                    "opportunity_edge": candidate.opportunity_edge,
                    "reasons": ["forced persisted rejection for drift test"],
                }
            ],
            "opportunity_context_snapshot": snapshot_payload,
        }
''',
    "drift fixture retains snapshot",
)
replace_once(
    '        identifier="publication:screening:canonical-adapter",\n',
    '        identifier=publication_identifier,\n',
    "publication identifier reuse",
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
replace_once(
    '        match="runtime opportunity ranking differs",\n',
    '        match="opportunity snapshot queue differs",\n',
    "drift failure expectation",
)
path.write_text(text, encoding="utf-8")
