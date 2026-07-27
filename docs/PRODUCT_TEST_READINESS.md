# Product Test Readiness

Capital Intelligence may become ready for a controlled paper-product test without stopping normal development. Testing uses an immutable baseline identifier, exact code commit, and versioned investment process. Later development continues on subsequent commits and cannot silently change the active test sample.

## States

- `development_in_progress` — development remains open and one or more test gates are incomplete.
- `blocked` — development was marked closed but required authorities still fail.
- `ready_for_controlled_paper_test` — one immutable baseline satisfies every required gate.

No state authorizes real money, broker connectivity, or performance claims.

## Required gates

The baseline must prove readiness for:

- the core U.S. market;
- governed crypto spot;
- governed unlevered spot FX;
- governed international listed equities;
- certified point-in-time data;
- complete-universe screening;
- production context assembly;
- portfolio construction;
- paper execution;
- living theses and evaluation;
- canonical daily operations;
- Today, Environment, Portfolio, and History;
- security validation;
- resilience exercises; and
- explicit paper-only disclosures.

It must also have zero unresolved critical incidents, data-integrity failures, and reconciliation failures.

## Open-development rule

Readiness freezes a **test baseline**, not the repository. Mainline development may continue. Any material decision-process change creates a new candidate baseline and cannot alter results already recorded under the prior baseline.

## Command

```bash
python run_test_readiness.py \
  --evidence artifacts/product-test-readiness.json \
  --require-ready
```

The command appends the report to a hash-chained SQLite history. Missing or false evidence is reported as a blocker rather than inferred or repaired.

## External boundary

The evaluator measures supplied evidence; it cannot create licensed provider access, certify real data, complete elapsed operating cycles, or fabricate resilience results. Those authorities must exist before their gates can be marked ready.
