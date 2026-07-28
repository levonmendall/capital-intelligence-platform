# Controlled Paper-Test Entry Governance

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

Repository authorities can prove that one immutable baseline satisfies the technical and operating requirements for a controlled paper test. They cannot approve that baseline by themselves. Entry requires a separate human release-authority decision tied to the exact eligibility package and a named test cohort.

Normal development remains open. The freeze applies only to the code, process, configuration, data manifest, operation plan, and stage bindings used by the controlled test baseline. Later commits cannot silently alter the active test sample.

## Three authorities

### 1. Investment-process freeze

`InvestmentProcessFreeze` records the reviewed test process and binds it to:

- baseline identifier;
- investment-process version;
- deployed code version;
- reviewed process-bundle SHA-256;
- canonical operation-plan SHA-256;
- production stage-binding SHA-256;
- configuration SHA-256;
- all-markets data-manifest identifier;
- investment-process governance identity;
- an independent validation identity;
- evidence and explicit limitations; and
- effective and expiry boundaries.

The process freeze requires the `investment_process_governance` role. The governance identity and independent validation identity must be different. A suspension, revocation, or expiration blocks entry.

The process bundle should include the governing specification, architecture, approved investment process, construction and execution policies, thesis and evaluation policies, risk constraints, data-scope policy, disclosures, and the controlled-test operating procedure. `canonical_process_bundle_sha256()` hashes the exact reviewed files and their names.

### 2. Eligibility package

`PaperTestEntryPackageAssembler` combines existing immutable authorities:

- active investment-process freeze;
- canonical product-test readiness report in `ready_for_controlled_paper_test` state;
- exact paper-test campaign baseline;
- satisfied multi-day burn-in and failure-campaign report;
- passed isolated canonical recovery drill;
- active exact production stage-binding approval; and
- matching baseline, process, code, plan, binding, configuration, data-manifest, and evidence lineage.

The resulting `ControlledPaperTestEligibilityPackage` is either `eligible` or `blocked`. It cannot authorize testing. A caller cannot override blockers, substitute another baseline, or alter the package without changing its fingerprint.

### 3. Human entry decision

`ControlledPaperTestEntryDecision` requires the `paper_test_release_authority` role, an independent validator, the exact eligibility-package identifier and fingerprint, a named cohort, rationale, limitations, and effective and expiry boundaries.

An approved decision authorizes only the named controlled paper-test cohort on the exact immutable baseline. It does not authorize:

- real money;
- broker connectivity;
- live orders;
- performance claims;
- changes to the CIO decision path; or
- later development commits.

A blocked eligibility package cannot be approved. A later suspension or revocation becomes the latest governing conclusion for that baseline.

## Separation of duties

The intended oversight functions are:

| Function | Responsibility |
| --- | --- |
| Investment-process governance | Freeze the exact process bundle and baseline inputs |
| Independent validation | Confirm process, model, evidence, and control integrity |
| Deployment governance | Approve the exact twelve-stage production binding document |
| Operations governance | Produce burn-in, incident, SLO, resilience, and recovery evidence |
| Paper-test release authority | Approve or block the exact eligibility package for a named cohort |

These are human oversight roles. They are not additional investment agents and do not vote on individual portfolio actions.

## Command workflow

Record a reviewed process freeze:

```bash
python run_paper_test_entry_governance.py \
  --record-freeze reviewed-process-freeze.json
```

Assemble the package from persisted authorities:

```bash
python run_paper_test_entry_governance.py \
  --assemble-package \
  --baseline-identifier test-baseline:universal-paper-alpha.1
```

Record the human entry decision:

```bash
python run_paper_test_entry_governance.py \
  --record-decision reviewed-entry-decision.json \
  --baseline-identifier test-baseline:universal-paper-alpha.1
```

Inspect current status:

```bash
python run_paper_test_entry_governance.py \
  --status \
  --baseline-identifier test-baseline:universal-paper-alpha.1
```

## Fail-closed behavior

Entry remains blocked when any required authority is missing, stale, expired, suspended, revoked, failed, belongs to another baseline, uses another process or code version, or has a mismatched digest. Governance history is append-only and SHA-256 chained.

## Remaining external work

This authority completes the repository-controlled approval mechanism. It does not fabricate the evidence it consumes. Before a real entry decision can be approved, the deployment still needs:

- selected and licensed providers;
- real credentials and approved data rights;
- completed point-in-time backfills and certifications;
- a reviewed production stage-binding document;
- real elapsed burn-in days;
- completed failure exercises;
- an actual encrypted backup and isolated restoration drill; and
- named human signatories for the required governance roles.
