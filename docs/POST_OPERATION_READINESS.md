# Post-Operation Readiness Publication

## Purpose

Operational readiness must be assessed only after the canonical daily operation reaches a terminal state. Publishing it inside the twelve-stage workflow would create a circular dependency: the operation would be evaluating its own completion before completion existed.

The daily command therefore uses this sequence:

```text
canonical daily operation claim
        ↓
twelve governed stages
        ↓
terminal completed or failed event
        ↓
post-operation operational-readiness assembly
        ↓
append-only OperationalReadinessSnapshot
```

The publication cannot alter the operation result. A completed investment operation remains completed even when the resulting operational snapshot contains readiness blockers.

## Immutable baseline binding

When `CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER` or `--test-baseline-identifier` is configured, the baseline identifier becomes an immutable input of the daily-operation claim.

The post-operation publisher refuses to use a baseline that was not present in that claim. The operational assembler then requires the same:

- baseline identifier;
- investment-process version; and
- code version.

This prevents a completed operation from being reassigned to a different test sample after the fact.

## Publication behavior

After `CanonicalDailyOperationsOrchestrator.run()` returns a terminal result, `PostOperationReadinessPublisher` reads:

- the just-finished daily operation and its terminal event;
- the current operational SLO snapshot;
- the latest resilience report; and
- unresolved critical incidents.

It persists an `OperationalReadinessSnapshot` through the append-only readiness-evidence authority.

A failed daily operation is also eligible for publication. Its failure classification remains visible in the snapshot rather than being omitted because the operation was unsuccessful.

## Blocked snapshots

Missing, stale, failed, mismatched, or integrity-invalid runtime evidence produces an honest blocked snapshot. It does not erase or rewrite the operation.

By default, the command returns the operation's status and includes the readiness publication in its JSON output. A controlled test deployment may add:

```bash
--require-clean-operational-readiness
```

That option returns a failing process status when the published snapshot contains blockers. It still does not change the canonical daily-operation event history.

## Deployment

Normal development does not need to configure a test baseline. In that mode, the daily operation runs without post-operation readiness publication.

For one immutable controlled-test baseline:

```text
CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER=test-baseline:multi-asset-alpha.1
CAPITAL_INTELLIGENCE_RELEASE=<tested-commit-sha>
CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION=<tested-process-version>
```

Then run:

```bash
python run_daily_operations.py \
  --loop \
  --require-clean-operational-readiness
```

The baseline environment value does not make the product test ready. It only binds operations and evidence to a candidate baseline. All separately governed readiness certifications remain required.

## Authority boundary

Post-operation publication cannot:

- certify a provider or dataset;
- approve an asset class;
- issue or change a CIO decision;
- alter portfolio construction or paper fills;
- fabricate SLO, resilience, incident, or operation evidence;
- self-approve a readiness gate;
- permit performance claims; or
- authorize real money.

Development remains open. A readiness decision applies only to an immutable baseline and exact process/code versions.
