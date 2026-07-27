# Controlled Paper-Test Burn-In and Failure Campaign

## Purpose

The campaign authority proves whether one immutable software and investment-process baseline has accumulated enough real operating evidence to be considered by human governance for controlled paper testing.

It does not approve the baseline, authorize real money, close development, or permit performance claims.

## Immutable baseline

A campaign baseline binds:

- investment-process version;
- deployed code version;
- twelve-stage operation-plan hash;
- reviewed stage-binding hash;
- deployment-configuration hash;
- all-markets data-readiness manifest identity;
- effective date;
- required consecutive operating days; and
- the complete required failure-scenario set.

Any change to those values creates a new baseline and restarts elapsed-day evidence. Prior evidence remains append-only but cannot be credited to the changed baseline.

## Creditable operating days

At most one day may be recorded for a baseline and calendar date. A day is creditable only when:

- it is not a future or synthetic date;
- the canonical daily operation completed;
- all twelve stages completed;
- every stage published canonical output identifiers;
- implementation and portfolio state reconciled;
- no duplicate alerts were emitted;
- no unresolved critical incident existed;
- no data-integrity failure existed;
- the day preserved its decision, portfolio, readiness, backup, and source identities; and
- an action day contains canonical implementation records, or a valid no-action day contains none.

A failed or incomplete day remains visible and blocks the campaign rather than being silently omitted.

## Required failure scenarios

Every baseline requires isolated, append-only evidence for:

1. provider outage and recovery;
2. stale or future-known data;
3. incomplete screening;
4. worker termination and fenced takeover;
5. database unavailability or locking;
6. database-corruption detection;
7. encrypted backup restoration;
8. execution hold and retry;
9. duplicate-alert suppression;
10. a valid no-action day; and
11. complete evidence-lineage reconstruction.

A passed scenario must run in an isolated environment, mutate production zero times, preserve detection/recovery/reconciliation evidence, and contain no unresolved error. A later retest may supersede an earlier failed attempt, but the failed attempt remains in history.

## Campaign state

The evaluator reports:

- `in_progress` when elapsed days or scenario evidence are still missing;
- `blocked` when an operating day or required scenario fails;
- `satisfied` when the required consecutive real days and every scenario pass; or
- `suspended` when governance pauses the campaign.

Even a satisfied campaign always reports:

```text
paper_test_authorized = false
real_money_authorized = false
performance_claims_permitted = false
```

A separate human-governed paper-test entry decision is still required.

## Commands

Create and review the baseline JSON, then record it:

```bash
python run_paper_test_campaign.py \
  --record-baseline reviewed-campaign-baseline.json
```

Record one completed operating day:

```bash
python run_paper_test_campaign.py \
  --record-day artifacts/burn-in-day-2026-07-27.json
```

Record one isolated scenario outcome:

```bash
python run_paper_test_campaign.py \
  --record-scenario artifacts/provider-outage-outcome.json
```

Assess the campaign:

```bash
python run_paper_test_campaign.py \
  --assess-baseline paper-baseline:alpha-1
```

Inspect all immutable evidence:

```bash
python run_paper_test_campaign.py \
  --inspect-baseline paper-baseline:alpha-1
```

The database defaults to `database/paper_test_campaign.db` and may be configured with `CAPITAL_INTELLIGENCE_PAPER_TEST_CAMPAIGN_DATABASE`. It is part of the canonical encrypted backup set.
