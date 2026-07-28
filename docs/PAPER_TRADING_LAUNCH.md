# Controlled Paper-Trading Launch

## Purpose

Passing unit tests and release validation does not authorize the controlled paper portfolio to begin operating. Paper execution requires three independent authorities for one exact immutable baseline, investment-process version, and tested code version:

1. the human-controlled paper-test entry decision;
2. sustained operational launch certification; and
3. the active runtime risk switch.

The authorities are non-substitutable. The launch remains paper-only and does not authorize real money, brokerage credentials, custody, external performance claims, or autonomous trading.

See `docs/CONTROLLED_PAPER_TEST_GOVERNANCE.md` for the process freeze, eligibility package, named cohort, and human entry decision. See `docs/PAPER_TRADING_AUTHORITY_MODEL.md` for the combined authority boundary.

## Canonical portfolio

Operational launch certification can be ready only when evidence confirms:

- exactly one portfolio;
- portfolio code `COMPOUNDING`;
- initial capital of `$250,000`;
- base currency `USD`;
- canonical portfolio, eligible-universe, and execution-store integrity;
- no live broker credentials; and
- paper-only disclosures on every active user surface.

## Minimum burn-in policy

`config/paper_trading_launch_policy.json` currently requires:

- at least five calendar days and five scheduled CIO cycles;
- every scheduled cycle successful;
- every cycle point-in-time valid and based on a complete published universe;
- at least 99% successful checks across required live providers;
- at least 12 shadow execution scenarios, all reconciled;
- execution-cost calibration error no greater than 25 basis points;
- zero unresolved orders, duplicate fills, negative-cash events, stale-quote acceptances, critical incidents, data-integrity failures, or reconciliation failures;
- successful backup/restore, scheduler replay, provider failover, partial-fill retry, corporate-action replay, and FX-revaluation exercises;
- at least two tested runtime halt-control exercises; and
- at least three market-session exercises covering distinct operating schedules.

The default paper circuit breakers are:

- maximum portfolio drawdown: 20%;
- maximum turnover in one execution batch: 35%; and
- operational launch-certification lifetime: 24 hours.

These are safeguards, not return targets or investment recommendations.

## Evidence contract

The evidence JSON must validate against:

```text
schemas/paper_trading_launch_evidence.schema.json
```

A non-authoritative format example is available at:

```text
docs/examples/paper_trading_launch_evidence.example.json
```

The example contains placeholders and must never be submitted as real evidence. Counts and identifiers must come from immutable operating reports and append-only source authorities.

## Evaluate operational launch health

```bash
python run_paper_trading_launch.py \
  --evidence reports/paper-trading-launch-evidence.json \
  --policy config/paper_trading_launch_policy.json \
  --database database/paper_trading_launch.db \
  --output reports/paper-trading-launch-report.json \
  --require-ready
```

The evaluator fails closed. A newer blocked assessment supersedes any older ready assessment for the same baseline, process, and code version. An expired report is unavailable.

## Human entry decision

The human release authority must separately approve the latest eligible package and named cohort through `run_paper_test_entry_governance.py`. A runtime switch cannot create or replace this approval. A later suspended, revoked, blocked, or expired human conclusion prevents execution immediately.

## Activate the runtime risk switch

Only after the human decision is approved and operational launch health is current may risk operations activate the runtime switch:

```bash
python run_paper_trading_control.py activate \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --identifier <UNIQUE_CONTROL_EVENT> \
  --reason "Enable runtime paper execution for the approved cohort" \
  --authority-identifier <RISK_OPERATIONS_AUTHORITY>
```

Activation verifies the latest human decision and eligibility-package fingerprint, then records the current operational launch report. The switch is an operational risk control only; it cannot approve entry.

## Halt immediately

```bash
python run_paper_trading_control.py halt \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --identifier <UNIQUE_HALT_EVENT> \
  --reason "Risk or operating condition requires suspension" \
  --authority-identifier <HALTING_AUTHORITY>
```

Missing runtime-control state means halted. A later halt supersedes an earlier activation. Reactivation requires the latest human entry approval and a still-current operational launch report.

## Canonical product-readiness check

```bash
python run_test_readiness.py \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --paper-launch-database database/paper_trading_launch.db \
  --require-ready
```

The product-readiness command cannot report the canonical baseline ready without sustained launch certification. Product readiness still does not grant human entry or activate the runtime switch.

## Execution enforcement

`run_multi_asset_paper_execution.py` requires:

- the latest eligible package;
- the latest active human approval referencing that exact package and fingerprint;
- a current operational launch report;
- an active runtime switch referencing that launch report;
- exact baseline, process, and code-version equality across all authorities;
- canonical portfolio, eligible-universe, and execution-store integrity;
- turnover within the launch circuit breaker; and
- drawdown within the launch circuit breaker.

The explicit development bypass is rejected in staging and production. It is never entry, launch, or performance evidence and never creates real-money authority.

## Backup and recovery

These append-only databases are mandatory canonical backup and recovery authorities:

```text
database/paper_test_governance.db
database/paper_trading_launch.db
database/paper_trading_control.db
```

A recovery drill must restore all three hash chains with portfolio, universe, execution, decision, readiness, and operational authorities. Losing any authority means paper execution remains halted until the complete reviewed authorization sequence is re-established.

## Remaining external work

This implementation creates the final internal launch controls. It does not fabricate the real evidence required to pass them. Before activation, the deployment must still provide:

- licensed and certified market-data providers;
- reviewed production bindings and credentials;
- completed historical backfills and reconciliation;
- execution-price and cost calibration against representative market conditions;
- the five-day live burn-in and required exercises;
- a passing encrypted recovery drill; and
- human approval of the exact eligibility package and named cohort.
