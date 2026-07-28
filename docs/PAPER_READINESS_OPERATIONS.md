# Paper-Readiness Operations

## Purpose

This runbook turns the remaining controlled paper-test objectives into executable, machine-readable operations. It does not manufacture provider contracts, elapsed operating days, recovery evidence, or human approval.

Run the consolidated status command at any point:

```bash
python run_paper_readiness_status.py \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --reconciliation-report reports/eodhd-reconciliation.json \
  --execution-calibration-report reports/execution-calibration.json \
  --recovery-report reports/recovery-drill.json \
  --require-complete
```

The command reports each of the eight objectives separately and never prints credential values. It returns nonzero while any objective is incomplete.

## 1. Licensed and certified market-data providers

`config/paper_readiness_provider_requirements.json` lists the explicit provider roles and the environment-variable names required for licensing, certification, credentials, and binding files.

A configured token is not evidence of a license. An endpoint response is not certification. The status command requires explicit approval and certification identifiers in addition to credentials.

The current required provider roles are:

- official FRED macro evidence;
- official SEC issuer evidence;
- EODHD broad historical multi-asset data;
- Coinbase and Kraken independent crypto evidence;
- survivorship-safe historical reference and corporate-action data;
- execution-grade non-crypto quotes; and
- evaluated fixed-income pricing.

The historical reference, execution-quote, and evaluated fixed-income roles remain external procurement decisions. Their missing approval, certification, and credential variables remain visible blockers.

## 2. Reviewed production bindings and credentials

Production stage bindings must pass both schema validation and exact digest approval:

```bash
python run_daily_stage_adapter.py \
  --validate-bindings \
  --bindings /run/secrets/canonical-daily-stage-bindings.json

python run_stage_binding_governance.py \
  --validate-bindings /run/secrets/canonical-daily-stage-bindings.json \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA>
```

Secrets are injected at runtime. Approval records contain variable names only. Any binding change requires a new digest approval.

## 3. Live provider smoke evidence

The repository now includes a credential-safe provider probe:

```bash
python run_provider_smoke.py \
  --require-fred \
  --output reports/provider-smoke.json
```

When EODHD has been purchased and configured:

```bash
python run_provider_smoke.py \
  --require-fred \
  --require-eodhd \
  --eodhd-bindings /run/secrets/eodhd-instrument-bindings.json \
  --output reports/provider-smoke.json
```

The GitHub workflow `.github/workflows/paper-readiness-provider-smoke.yml` injects the existing `FRED_API_KEY` repository secret and runs the official FRED probe without exposing the key. Scheduled execution remains disabled until the repository variable below is set:

```text
PAPER_READINESS_AUTOMATION_ENABLED=true
```

Optional EODHD enforcement uses:

```text
PAPER_READINESS_REQUIRE_EODHD=true
```

The EODHD token should be stored as `CAPITAL_INTELLIGENCE_EODHD_API_TOKEN`. Its binding JSON may be stored as the protected secret `CAPITAL_INTELLIGENCE_EODHD_BINDINGS_JSON` for this smoke workflow. Deployment should continue using a mounted secret file.

A successful smoke report proves access only. It deliberately sets licensing and certification to false.

## 4. Backfills and reconciliation

Run the reviewed immutable backfill plan:

```bash
python run_provider_backfill.py \
  --plan config/eodhd_backfill_plan.json \
  --output-directory data/provider-backfills/eodhd-reviewed
```

Then reconcile every landed artifact:

```bash
python run_provider_reconciliation.py \
  --backfill-directory data/provider-backfills/eodhd-reviewed \
  --output reports/eodhd-reconciliation.json \
  --require-passed
```

Reconciliation verifies:

- the backfill completed without required failures;
- artifact count and manifest identity;
- immutable file hashes;
- raw provider-payload hashes;
- provider, symbol, dataset, and interval identity;
- point-in-time availability and retrieval ordering;
- safe relative paths; and
- duplicate logical windows.

Empty provider payloads are disclosed as warnings because some valid corporate-action windows may contain no events. Reviewers must still confirm expected record counts, coverage, currencies, calendars, identifiers, and economic plausibility.

## 5. Execution-price and cost calibration

Collect representative independent quote evidence and the corresponding modeled paper fills in `paper-execution-calibration-input.v1` format. Validate the input against:

```text
schemas/execution_calibration_input.schema.json
```

Evaluate it:

```bash
python run_execution_calibration.py \
  --input reports/execution-calibration-input.json \
  --policy config/execution_calibration_policy.json \
  --output reports/execution-calibration.json \
  --require-passed
```

The default policy requires:

- at least 12 samples;
- at least three asset classes;
- quote age no greater than 60 seconds;
- mean absolute modeled-cost error no greater than 15 basis points;
- 95th-percentile error no greater than 25 basis points; and
- no single sample above 50 basis points.

The 95th-percentile error feeds the launch evidence as `execution_cost_error_bps`. Calibration must use independently observed market evidence; synthetic fixtures prove code behavior only.

## 6. Five-day live burn-in and exercises

The existing campaign authority records actual completed days and failure exercises:

```bash
python run_paper_test_campaign.py --record-baseline reviewed-baseline.json
python run_paper_test_campaign.py --record-day completed-day.json
python run_paper_test_campaign.py --record-scenario completed-scenario.json
python run_paper_test_campaign.py \
  --assess-baseline <IMMUTABLE_BASELINE>
```

Days cannot be pre-created or backdated into existence. Each credited day requires all twelve stages, point-in-time output lineage, reconciliation, canonical portfolio evidence, backup identity, zero critical incidents, and zero data-integrity failures.

The required failure campaign includes provider outage, stale or future data, incomplete screening, fenced worker takeover, unavailable or corrupted databases, encrypted backup restore, execution hold and retry, duplicate-alert suppression, valid no-action handling, and evidence-lineage reconstruction.

## 7. Encrypted recovery drill

Create a complete encrypted canonical backup on the target deployment:

```bash
python run_backup.py
```

Then run the isolated recovery drill using the exact reviewed expectation:

```bash
python run_recovery_drill.py \
  --archive <ENCRYPTED_BACKUP_ARCHIVE> \
  --expectation reviewed-recovery-expectation.json \
  --report-database database/recovery_drills.db \
  > reports/recovery-drill.json
```

A passing report must restore every required authority, pass SQLite integrity checks and lineage probes, meet recovery-time and recovery-point objectives, and record zero production mutations. Repository tests cannot substitute for this deployment-specific drill.

## 8. Human approval and runtime activation

After every technical objective is complete, assemble and inspect the exact eligibility package through the existing paper-test entry governance command. A person holding the `paper_test_release_authority` role, with a distinct independent validator, must approve the exact package fingerprint and named cohort.

The assistant, CI, provider adapter, and runtime switch must not impersonate that authority.

After the human decision is active and launch health remains current, risk operations may activate the runtime switch:

```bash
python run_paper_trading_control.py activate \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --identifier <UNIQUE_RUNTIME_EVENT> \
  --reason "Enable controlled paper execution for the approved cohort" \
  --authority-identifier <RISK_OPERATIONS_AUTHORITY>
```

The activation command verifies the latest human decision, exact eligibility-package fingerprint, and current launch certification before recording the active event.

## Completion boundary

The following work is completed by this implementation:

- the existing FRED secret is wired into a protected live smoke workflow;
- provider access can be probed without secret disclosure;
- backfills can be cryptographically reconciled;
- execution cost can be measured against independent quote evidence;
- all eight objectives can be reported together from persisted authorities; and
- incomplete external or human prerequisites remain explicit blockers.

The repository still cannot purchase contracts, accept vendor legal terms, create missing historical data, wait five calendar days instantly, generate a genuine deployment backup without deployment databases, or issue human approval.
