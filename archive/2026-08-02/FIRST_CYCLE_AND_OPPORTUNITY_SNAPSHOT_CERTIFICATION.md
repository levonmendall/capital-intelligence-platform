# First-Cycle Persistence and Opportunity Snapshot Certification

## Protected invariants

This change does not alter the canonical investment strategy, return thresholds, evidence thresholds, liquidity controls, downside limits, cash hurdle, specialist authority, CIO-only authority, construction authority, paper-execution authority, or prohibition on real-money trading.

## First-cycle persistence contract

The resolved decision-policy profile is the sole authority for persistence requirements.

- A first valid observation counts as cycle one.
- A one-cycle entry profile may act on the first observation.
- A two-cycle entry profile defers the first observation and preserves the intended action in append-only history.
- The second action may proceed only when the required supportive sequence exists.
- Participation and exploration retain their explicit risk-capped one-cycle treatment.
- Emergency de-risking remains immediate.
- An existing holding without reconstructable thesis continuity cannot be ordinarily increased or reduced on its first observation. A continuity thesis is created when the first governed action is a deferred HOLD.

## Immutable opportunity authority

Each production screening publication stores a canonical, SHA-256-guarded parent snapshot containing the exact point-in-time opportunity context and preliminary queue. Before specialist and CIO review, the production executor stores a portfolio-ranked child snapshot in the append-only CIO journal.

The snapshots preserve:

- every cash, holding, and qualified-candidate alternative;
- expected and net return, costs, evidence quality, liquidity, and current weight;
- ranking inputs and score components;
- qualification outcomes and reasons;
- baseline and best-alternative identifiers and comparable returns;
- resolved policy and model versions;
- code version, publication identity, parent hash, and content hash.

Runtime must verify snapshot hashes, candidate coverage, publication identity, timestamps, exact portfolio baseline, context identity, and parent-child lineage. Retries consume the existing child snapshot. They do not rebuild an old decision queue with newer code.

An explicitly configured deployment-version mismatch before the child snapshot exists fails closed and requires a new publication. Ambient CI merge references are not treated as deployment-version authority.

## State and migration

No historical journal event, screening publication, portfolio snapshot, thesis, or order record is rewritten. The contract applies prospectively. Older publications remain readable but are not exact-snapshot certified.

## Rollback

Revert the implementation commit. No database migration, portfolio reset, or historical rewrite is required.
