# Canonical CIO Journal and Decision Replay

`SQLiteCIOJournal` provides append-only, tamper-evident persistence for the canonical investment-decision loop.

It may use the same SQLite file as the earlier institutional journal, but it writes to a dedicated `cio_journal_events` table and maintains its own contiguous SHA-256 chain. This allows the canonical schema to be added without rewriting or reinterpreting older regime, portfolio-fit, or decision-quality records.

## Event sequence

The ledger supports:

1. `candidate_decision` — the quantitative point-in-time candidate package;
2. `opportunity_queue` — qualified rankings and explicit rejections;
3. `specialist_packet` — all five independent analyses, vetoes, implementation blocks, and strongest dissent;
4. `cio_decision` — the final CIO action or disciplined abstention;
5. `thesis_snapshot` — an immutable state of the living thesis; and
6. `thesis_review` — a monitoring conclusion and CIO-review proposal.

The sequence records what the platform knew, what alternatives it considered, what specialists concluded, what the CIO decided, how the thesis changed, and what happened afterward.

## Integrity controls

The database installs triggers that reject `UPDATE` and `DELETE` statements on canonical CIO events.

Each event stores:

- a global sequence number;
- event and aggregate identifiers;
- event type;
- occurrence and recording timestamps;
- schema version;
- canonical sorted JSON;
- the previous event hash; and
- its own SHA-256 content hash.

`verify_integrity()` recalculates every hash, verifies sequence continuity, and verifies every previous-hash link. Out-of-band mutation is detected even if a database trigger is bypassed or removed.

## Idempotency

Re-appending the same event identifier with exactly the same content returns the existing event. Reusing an event identifier with different content is rejected.

This allows retry-safe scheduled workflows without permitting historical mutation.

## Candidate replay

The candidate payload preserves:

- instrument and listing facts;
- Version 1 asset classification inputs;
- price and decision timestamp;
- scenario returns and probabilities;
- probability-weighted and cost-adjusted expected return;
- fair value, upside, downside, and success probability;
- supporting and contradictory evidence;
- all evidence-quality dimensions and the confidence ceiling;
- liquidity, costs, slippage, opportunity cost, and portfolio contribution;
- assumptions, invalidation conditions, and monitoring indicators;
- evidence identifiers, model versions, and code version.

## Opportunity replay

The opportunity event preserves both ranked and rejected candidates. Each ranking component retains its raw value, normalized score, weight, and contribution. Rejections preserve universe disposition, effective opportunity cost, opportunity edge, and every rejection reason.

## Committee and CIO replay

The specialist packet preserves the five independent first-pass analyses, role-specific authority, evidence vetoes, implementation blocks, proposed size and funding, support diagnostics, and strongest dissent.

The CIO event preserves the final action, confidence, expected return, position proposal, funding source, thesis, evidence, assumptions, risks, invalidation conditions, portfolio impact, opportunity-cost explanation, dissent, vetoes, blocks, monitoring indicators, review date, explanation, policy version, and code version.

## Thesis replay

Every thesis review and resulting thesis snapshot is appended. The original rationale and assumptions are never rewritten. Later evidence updates expected return, downside, confidence, performance, evidence identifiers, state, and review timing through new events.

## Boundary

The journal records decisions. It does not create candidates, rank opportunities, analyze evidence, issue actions, size positions, monitor markets, or execute trades. Serializers are deterministic presentation of already validated domain records.