# Operational Readiness Assembly

## Purpose

Product test readiness requires current operational facts, not a manually prepared operational snapshot. The repository therefore assembles operational evidence from four canonical authorities:

```text
canonical daily operations
+ operational SLO snapshots
+ resilience exercise reports
+ operational incident history
        ↓
OperationalReadinessSnapshot
        ↓
persisted readiness evidence
        ↓
separate governed test-readiness evaluation
```

The assembler does **not** approve a test-readiness gate. It records current facts so a reviewed gate certification cannot hide a failed daily operation, stale SLO assessment, failed resilience campaign, broken integrity chain, or unresolved critical incident.

## Daily-operation authority

The assembler selects the latest operation available at the assessment timestamp whose immutable claim exactly matches:

- test baseline identifier in `input_identifiers`;
- investment-process version; and
- code version.

A different baseline, process, or code version cannot be substituted. The operation must have a terminal event and must remain within the configured freshness boundary.

A failed operation preserves its failure classification. `integrity` and `data_quality` become data-integrity failures. `reconciliation` becomes a reconciliation failure. Any incomplete or failed operation is also a current critical operational blocker.

## SLO authority

`SQLiteOperationalSLOStore` remains the source of operational SLO truth. Its chain must verify, its latest snapshot must not be future-known or stale, and `ready` must be true. A breached component and its affected identifiers remain visible in the snapshot lineage.

## Resilience authority

`SQLiteResilienceExerciseStore` remains the source of resilience truth. Its append-only chain must verify. The latest report must be current and its release gate must pass. The operational snapshot preserves the report and outcome identifiers.

A passed resilience report is still not a product-test approval. The separate resilience gate certification remains baseline-, process-, and code-specific.

## Incident authority

`SQLiteOperationalIncidentStore` is an append-only SHA-256 incident history. An incident is opened once and may be closed only by a later explicit resolution event. Resolved incidents cannot be silently reopened under the same identifier.

Each incident event preserves:

- incident and event identifiers;
- severity and state;
- detection and transition timestamps;
- classification and summary;
- baseline, process, and code versions;
- source identifiers; and
- explicit resolution identity when resolved.

Every open critical incident at the assessment timestamp contributes to `unresolved_critical_incidents`.

## Fail-closed snapshot

The assembler always persists an honest snapshot, including when sources are missing or invalid. Each current blocker contributes to the unresolved-critical count and is preserved as an `operational-blocker:` source identifier.

The snapshot contains:

- exact baseline, process, and code versions;
- observation and knowledge-cutoff timestamps;
- unresolved critical incidents and blockers;
- data-integrity failures;
- reconciliation failures; and
- all supporting source identifiers.

A missing source never produces a clean snapshot.

## Commands

Record an incident transition:

```bash
python run_operational_incident.py \
  --event artifacts/incident-event.json
```

Assemble current operational evidence:

```bash
python run_operational_readiness.py \
  --baseline-identifier test-baseline:multi-asset-alpha.1 \
  --process-version capital-intelligence-investment-process.v1 \
  --code-version <tested-commit-sha> \
  --require-clean
```

The operational-evidence-review stage of the canonical daily plan may call this command after outcome evaluation and before the final readiness review. It must not be configured as a substitute for security testing, resilience exercises, or human gate certification.

## Authority boundary

Operational assembly cannot:

- issue or alter an investment decision;
- approve an asset class;
- certify a provider or dataset;
- fabricate a completed operation or resilience result;
- resolve an incident without a recorded resolution event;
- make performance claims;
- authorize real money; or
- declare the product test ready by itself.

Development remains open. Readiness applies only to an immutable test baseline.
