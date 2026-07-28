# Controlled Paper-Trading Launch

## Purpose

Passing unit tests and release validation does not authorize the controlled paper portfolio to begin operating. The launch authority requires sustained, point-in-time operating evidence for one exact immutable baseline, investment-process version, and tested code version.

The launch remains paper-only. It does not authorize real money, brokerage credentials, custody, external performance claims, or autonomous trading.

## Canonical portfolio

A launch can be ready only when the operating evidence confirms:

- exactly one portfolio;
- portfolio code `COMPOUNDING`;
- initial capital of `$250,000`;
- base currency `USD`;
- canonical portfolio, eligible-universe, and execution-store integrity;
- no live broker credentials;
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
- at least two tested global halt-control exercises;
- at least three market-session exercises covering distinct operating schedules.

The default paper circuit breakers are:

- maximum portfolio drawdown: 20%;
- maximum turnover in one execution batch: 35%;
- launch authorization lifetime: 24 hours.

These are launch safeguards, not return targets or investment recommendations.

## Evidence contract

The evidence JSON must validate against:

```text
schemas/paper_trading_launch_evidence.schema.json
```

A non-authoritative format example is available at:

```text
docs/examples/paper_trading_launch_evidence.example.json
```

The example contains placeholders and must never be submitted as real evidence. Counts and identifiers must be derived from immutable operating reports and append-only source authorities.

## Evaluate the launch

```bash
python run_paper_trading_launch.py \
  --evidence reports/paper-trading-launch-evidence.json \
  --policy config/paper_trading_launch_policy.json \
  --database database/paper_trading_launch.db \
  --output reports/paper-trading-launch-report.json \
  --require-ready
```

The evaluator fails closed. A blocked assessment supersedes any older ready assessment for the same baseline, process, and code version. Expired authorization is unavailable.

## Activate controlled paper execution

After the launch report is reviewed, an authorized human authority activates the exact launch:

```bash
python run_paper_trading_control.py activate \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --identifier <UNIQUE_CONTROL_EVENT> \
  --reason "Approved controlled paper-test activation" \
  --authority-identifier <APPROVING_AUTHORITY>
```

Activation requires a current ready launch report. The control event records the exact report it activates.

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

Missing control state means halted. A later halt supersedes an earlier activation. Reactivation requires a still-current launch report and a new append-only activation event.

## Canonical product-readiness check

```bash
python run_test_readiness.py \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --paper-launch-database database/paper_trading_launch.db \
  --require-ready
```

The product-readiness command cannot report the canonical controlled test ready without the sustained launch authority.

## Execution enforcement

`run_multi_asset_paper_execution.py` requires:

- a current launch report;
- an active control event referencing that report;
- exact baseline, process, and code-version equality;
- canonical portfolio, eligible-universe, and execution-store integrity;
- turnover within the launch circuit breaker;
- drawdown within the launch circuit breaker.

The explicit development bypass is rejected in staging and production. It is never launch evidence and never creates real-money authority.

## Backup and recovery

The append-only databases below are mandatory canonical backup and recovery authorities:

```text
database/paper_trading_launch.db
database/paper_trading_control.db
```

A recovery drill must restore their hash chains along with portfolio, universe, execution, decision, readiness, and operational authorities. Losing either database means paper execution remains halted until a new reviewed launch is established.

## Remaining external work

This implementation creates the final internal launch controls. It does not fabricate the real evidence required to pass them. Before activation, the deployment must still provide:

- licensed and certified market-data providers;
- reviewed production bindings and credentials;
- completed historical backfills and reconciliation;
- execution-price and cost calibration against representative market conditions;
- the five-day live burn-in and required exercises;
- a passing encrypted recovery drill;
- human review and activation of the exact baseline.
