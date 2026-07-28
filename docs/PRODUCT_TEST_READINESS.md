# Product Test Readiness

Capital Intelligence may become ready for a controlled paper-product test without stopping normal development. Testing uses an immutable baseline identifier, exact code commit, and versioned investment process. Later development continues on subsequent commits and cannot silently change the active test sample.

## States

- `development_in_progress` — development remains open and one or more test gates are incomplete.
- `blocked` — development was marked closed but required authorities still fail.
- `ready_for_controlled_paper_test` — one immutable baseline satisfies every required gate and has a current sustained launch authorization.

No state authorizes real money, broker connectivity, or performance claims.

## Required gates

The baseline must prove readiness for:

- the core U.S. market;
- universal governed-market capability across international equities, fixed income, commodities, FX, crypto, real estate, futures, options, volatility, and liquid alternatives;
- certified point-in-time data;
- complete-universe screening;
- production context assembly;
- portfolio construction;
- paper execution;
- living theses and evaluation;
- canonical daily operations;
- Today, Environment, Portfolio, and History;
- security validation;
- resilience exercises;
- explicit paper-only disclosures; and
- a current sustained paper-launch authorization.

It must also have zero unresolved critical incidents, data-integrity failures, and reconciliation failures.

## Canonical evidence authorities

A caller-supplied set of readiness booleans is not authoritative.

`SQLiteReadinessEvidenceStore` persists:

- immutable gate certifications; and
- point-in-time operational-readiness snapshots.

Every gate certification is bound to:

- one test baseline identifier;
- one investment-process version;
- one code version;
- effective and expiration timestamps;
- evidence identifiers;
- governing authority identifiers; and
- limitations.

Every governed non-core market gate additionally requires an active `paper_eligible` asset-class approval with the same process and code versions. A readiness certification cannot substitute for the asset-class governance authority.

The operational snapshot records unresolved critical incidents, data-integrity failures, reconciliation failures, and their source identifiers. A missing or stale snapshot forces daily-operations, security, and resilience gates to fail closed.

`SQLitePaperTradingLaunchStore` separately persists the sustained burn-in conclusion. It proves that the exact baseline completed the required live cycles, provider checks, shadow executions, reconciliations, recovery exercises, and circuit-breaker tests. A newer blocked or expired launch assessment supersedes every older approval.

## Automatic assembly

The default command assembles readiness from persisted authorities:

```bash
python run_test_readiness.py \
  --baseline-identifier test-baseline:multi-asset-alpha.1 \
  --process-version capital-intelligence-investment-process.v1 \
  --code-version <tested-commit-sha> \
  --paper-launch-database database/paper_trading_launch.db \
  --require-ready
```

The assembler requires exact baseline, process, and code matches. Missing, expired, suspended, revoked, stale, or mismatched evidence becomes a blocker or open development item; it is never inferred or repaired.

Record one reviewed gate certification:

```bash
python run_test_readiness_evidence.py \
  --gate-certification artifacts/readiness-gate.json
```

Record one operational snapshot:

```bash
python run_test_readiness_evidence.py \
  --operational-snapshot artifacts/operational-readiness.json
```

Evaluate and persist the sustained launch evidence:

```bash
python run_paper_trading_launch.py \
  --evidence artifacts/paper-trading-launch-evidence.json \
  --policy config/paper_trading_launch_policy.json \
  --require-ready
```

Gate evidence, launch history, global paper-control history, and resulting readiness reports are append-only and SHA-256 chained.

## Manual compatibility mode

Legacy caller-supplied evidence remains available only through an explicit option:

```bash
python run_test_readiness.py \
  --manual-evidence artifacts/product-test-readiness.json
```

The output is labeled `manual_compatibility`. It is not the canonical path for declaring a test baseline ready, cannot activate execution, and does not replace the launch or global control authorities.

## Open-development rule

Readiness freezes a **test baseline**, not the repository. Mainline development may continue. Any material decision-process change creates a new candidate baseline and cannot alter results already recorded under the prior baseline.

## External boundary

The assembler cannot create licensed provider access, certify real data, complete elapsed operating cycles, calibrate execution costs, or fabricate recovery and resilience results. Those authorities must persist valid evidence before their gates can become ready. Development remains open and real-money execution remains unavailable in every readiness state.

See `docs/PAPER_TRADING_LAUNCH.md` for the burn-in, activation, halt, circuit-breaker, and backup procedure.
