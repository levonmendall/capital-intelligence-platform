# Extended Paper-Operation Evidence

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The paper-operation evidence authority measures whether the complete governed process has accumulated enough intact and operationally credible paper evidence for a **formal human governance review**. It does not approve real-money execution, certify alpha, permit performance claims, modify models, or relax any investment or operating constraint.

## Readiness states

- `insufficient_evidence` — the observed process is not currently failing a control, but duration, regimes, decisions, calibration samples, implementation samples, or alert feedback remain too limited.
- `blocked` — required operating quality failed, including cycle completion, evaluation coverage, thesis-review coverage, paper implementation, reconciliation, data integrity, critical SLOs, incidents, calibrated confidence, or alert false-positive controls.
- `ready_for_governance_review` — the configured sample and control requirements are satisfied. This state only opens a human review; it does not authorize live capital.

Every report permanently returns:

```text
real_money_authorized = false
performance_claims_permitted = false
```

## Immutable observation contract

Each `PaperOperationObservation` preserves one non-overlapping period with:

- expected and completed full-universe cycles;
- CIO actions plus abstention and no-action decisions;
- decisions due and completed for point-in-time evaluation;
- confidence samples, Brier-score totals, and calibration error;
- paper execution batches, completion, reconciliation, failures, turnover, and costs;
- thesis reviews and strengthening, stable, weakening, or invalidated outcomes;
- generated, sent, suppressed, acknowledged, useful, and false-positive alerts;
- portfolio, benchmark, cash, and passive reference returns;
- critical SLO breaches, unresolved incidents, integrity failures, and reconciliation failures; and
- exact journal, SLO, execution, provider, or report identifiers supporting the observation.

Observation timestamps preserve when the period ended and when its evidence became available. Future-known or overlapping observations are rejected.

## Versioned release policy

`paper-operation-evidence.v1` defines configurable minimums for:

- observation days;
- distinct market regimes;
- completed full-universe cycles;
- CIO decisions;
- confidence samples;
- paper execution batches;
- alert feedback samples;
- cycle, evaluation, thesis-review, implementation, and reconciliation coverage;
- maximum alert false-positive rate;
- maximum mean Brier score and calibration error; and
- maximum critical SLO breaches, unresolved incidents, data-integrity failures, and reconciliation failures.

Low return or benchmark underperformance is not an automatic blocker. Portfolio return versus the benchmark, cash, and passive portfolio remains diagnostic evidence for the governance committee. This prevents a short favorable or unfavorable market period from automatically rewriting approval policy.

## Append-only evidence

`SQLitePaperOperationEvidenceStore` maintains independent SHA-256 chains for observations and assessments. Identifiers are idempotent only for identical payloads. SQLite triggers prohibit updates and deletes. Integrity must pass before any new observation or report is appended.

## Command

```bash
python run_paper_operation_review.py \
  --observation artifacts/paper-operation-observation.json \
  --record-report
```

A stricter scheduled or release check can fail closed:

```bash
python run_paper_operation_review.py \
  --observation artifacts/paper-operation-observation.json \
  --policy deploy/paper-operation-policy.json \
  --record-report \
  --require-governance-ready
```

Observation files may contain one object or a list and may be supplied repeatedly. Production collectors remain responsible for deriving each observation from verified canonical journal, SLO, screening, thesis-monitoring, paper-execution, alert, market, and benchmark records. The evidence authority will not invent or silently repair missing source data.

## Governance boundary

A `ready_for_governance_review` report is one input to a later formal release package. Human reviewers must still examine decision quality, abstention quality, confidence calibration, benchmark attribution, implementation costs, drawdowns, alert usefulness, incident exercises, known limitations, and provider coverage. Broker integration remains a separate permissioned project after explicit approval.
