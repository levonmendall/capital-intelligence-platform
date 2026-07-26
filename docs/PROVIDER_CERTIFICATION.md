# Security-Master Provider Certification

## Purpose

A provider adapter is not investment authority. Before any security-master catalog can power complete-universe screening, the provider must pass a current, append-only certification that independently verifies both its commercial rights and its point-in-time behavior.

Certification produces one of three decisions:

- **approved** — every mandatory manifest capability and required scenario passed;
- **conditionally approved** — mandatory checks passed, but one or more optional scenarios failed; or
- **rejected** — a mandatory capability or required scenario failed.

Only **approved** is eligible for activation. Conditional approval is useful for remediation planning but cannot authorize screening.

## Capability manifest

The machine-readable manifest is governed by [`schemas/security_master_provider_manifest.schema.json`](../schemas/security_master_provider_manifest.schema.json). It declares:

- provider and product identity;
- source and manifest versions;
- verified commercial-license reference;
- complete eligible-universe coverage;
- point-in-time delivery semantics;
- historical identifiers;
- listing and venue history;
- delisted securities;
- corporate actions;
- revision history;
- provenance completeness;
- cross-venue adjustment policy;
- service-level reference and maximum delivery age; and
- manifest validity dates.

A boolean claim is not accepted merely because it appears in a manifest. The certification suite must exercise the corresponding behavior with known historical examples.

## Acceptance scenarios

The suite schema is [`schemas/security_master_provider_certification_suite.schema.json`](../schemas/security_master_provider_certification_suite.schema.json). Required scenario kinds include:

- current and historical identity;
- symbol and venue changes;
- delistings;
- mergers and spinoffs;
- late corrections and revision history;
- future-knowledge exclusion;
- cross-venue adjustment behavior; and
- full-universe population coverage.

Each scenario specifies an economic `as_of`, a `knowledge_cutoff`, and the later request timestamp. Expected and excluded symbols, venue-listing states, action types, population floors, and future-known-record tolerances are evaluated deterministically.

## Execution

A provider package exposes a zero-argument factory returning `SecurityMasterProvider`:

```bash
python run_provider_certification.py \
  --provider-factory vendor_adapter:create_provider \
  --manifest provider-manifest.json \
  --suite provider-certification-suite.json \
  --identifier provider-certification:vendor:2026-07-26 \
  --certified-at 2026-07-26T18:00:00+00:00
```

Exit codes are:

- `0` — approved;
- `2` — conditionally approved;
- `3` — rejected; and
- `4` — execution, provider, manifest, suite, or persistence error.

The report is stored in `SQLiteProviderCertificationStore`, which is append-only and SHA-256 hash chained. Reusing an identifier with different content is rejected.

## Activation enforcement

`SecurityMasterIngestionService` requires the latest report for the catalog source to be:

- present;
- approved;
- unexpired;
- provider-matched; and
- integrity-valid.

The certification identifier, decision, and expiration are copied into the activation quality record. `active_catalog()` rechecks the latest report on every read. A later rejected report, expired report, missing registry, or tampered registry immediately makes the active catalog unavailable without deleting prior ingestion or activation history.

## Renewal and revocation

Certification is time-limited. It must be rerun when:

- the commercial contract or permitted use changes;
- the provider product or source version changes materially;
- identifier, listing, corporate-action, or correction semantics change;
- the cross-venue policy changes;
- the SLA changes;
- a material reconciliation conflict is discovered; or
- the current report approaches expiration.

Revocation is represented by appending a later rejected report. History is never rewritten.

## Current repository boundary

The repository supplies the certification authority, schemas, CLI, examples, persistence, and activation enforcement. It does not include a commercial vendor contract, credentials, or fabricated approval. The SEC current ticker feed remains uncertified and cannot activate full-universe screening.
