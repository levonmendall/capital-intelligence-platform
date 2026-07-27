# Incident, Recovery, and Reconciliation Exercises

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The resilience-exercise authority proves that operational failures are detected, contained, recovered, and reconciled without rewriting evidence or mutating production during the exercise. It has no investment or execution authority.

## Required Version 1 scenarios

`resilience-exercise-policy.v1` requires isolated exercises for:

1. provider outage;
2. stale data;
3. conflicting source values;
4. database corruption;
5. missed complete-universe cycle;
6. failed thesis review;
7. delayed decision evaluation;
8. partial paper execution;
9. encrypted backup restoration; and
10. model or policy rollback.

A production-scale campaign may add scenarios, but it may not remove a required scenario without a new reviewed policy version.

## Passing standard

Each scenario must preserve immutable evidence for four boundaries:

- **Injection** — the exact fault, isolated target, start time, and pre-exercise fingerprint.
- **Detection** — the alert, SLO, integrity, or reconciliation evidence that identified the fault within policy.
- **Recovery** — the controlled action and evidence that restored service within policy.
- **Reconciliation** — proof that the post-recovery fingerprint and all declared invariants equal the pre-exercise state.

A passing outcome also requires:

- an isolated environment;
- zero production mutations;
- complete detection, recovery, and reconciliation evidence identifiers;
- all scenario invariants verified; and
- every phase completed within its explicit deadline.

Provider exceptions, unavailable sandboxes, late phases, missing invariants, non-isolated execution, production mutations, or fingerprint mismatches block the release gate.

## Append-only evidence

`SQLiteResilienceExerciseStore` records exercise outcomes and campaign reports in one contiguous SHA-256 chain. Identical replay is idempotent, conflicting identifier reuse is rejected, and SQLite triggers prevent update and deletion.

Historical failures remain evidence. A later successful campaign does not erase them.

## Command

```bash
python run_resilience_exercises.py \
  --suite deploy/resilience-suite.json \
  --provider production_resilience_adapter:create_provider \
  --record \
  --require-passed
```

The provider factory must execute scenarios inside an isolated sandbox and return typed evidence. The core harness does not invent successful results or interact with a broker.

## Release boundary

`release_gate_passed=true` means the reviewed exercise suite passed the current resilience policy. It does not prove investment performance, authorize a production data provider, approve real-money execution, or replace formal governance approval. Every report permanently preserves `real_money_authorized=false`.
