# Production Stage-Binding Governance

## Purpose

The canonical daily plan defines the twelve stages and their dependency order. The deployment binding document supplies the reviewed command module, arguments, output contract, timeout, and retry behavior for each stage.

A binding document is executable configuration. Production must not run it merely because it is syntactically valid. It requires an immutable, active approval for the exact canonical JSON SHA-256 digest.

## Approved identity

A `StageBindingApproval` binds:

- the exact binding-document SHA-256;
- controlled paper-test baseline identity;
- investment-process version;
- deployed code version;
- approved command modules;
- required secret-variable names;
- effective and expiration timestamps;
- governance record and approver role; and
- rationale and limitations.

Approvals may be issued only by the `deployment_governance` or `operations_governance` role. The authority is append-only. A later suspension, revocation, or expired event supersedes any earlier approval for the same digest.

An approval never authorizes real-money activity.

## Secret boundary

The approval stores secret-variable names, not secret values. The binding document may refer to deployment variables such as `${PROVIDER_TOKEN}`, but it may not embed API keys, passwords, bearer tokens, private keys, or literal secret assignments.

At startup, the system verifies that every required secret-variable name exists. It does not persist or print the value.

## Production enforcement

Set:

```text
CAPITAL_INTELLIGENCE_STAGE_BINDING_APPROVAL_DATABASE=database/stage_binding_approvals.db
CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER=<approved-baseline>
CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION=<approved-process>
CAPITAL_INTELLIGENCE_RELEASE=<deployed-commit>
```

Once the approval database is configured, both startup validation and every stage execution fail closed unless:

1. the binding document contains all twelve canonical stages;
2. its exact digest has an active approval;
3. baseline, process, and code versions match;
4. every command module is approved;
5. every required secret variable is configured; and
6. no argument embeds a secret value.

Development and repository validation remain compatible when the approval database is not configured. Production configuration enables the approval authority by default.

## Review and record procedure

First validate the binding schema:

```bash
python run_daily_stage_adapter.py \
  --validate-bindings \
  --bindings /run/secrets/canonical-daily-stage-bindings.json
```

Generate the canonical digest during review:

```bash
python run_stage_binding_governance.py \
  --inspect-bindings /run/secrets/canonical-daily-stage-bindings.json
```

Create a reviewed `stage-binding-approval.v1` JSON document containing the digest, exact deployment identity, allowed modules, secret-variable names, expiration, approver role, and rationale. Record it:

```bash
python run_stage_binding_governance.py \
  --record-approval reviewed-stage-binding-approval.json
```

Validate the exact deployment combination:

```bash
python run_stage_binding_governance.py \
  --validate-bindings /run/secrets/canonical-daily-stage-bindings.json \
  --baseline-identifier paper-baseline:alpha-1 \
  --process-version capital-intelligence-investment-process.v1 \
  --code-version <deployed-commit>
```

## Change control

Any change to a module, argument, timeout, retry code, output field, or stage binding changes the digest and requires a new approval. Secret rotation does not require a new digest when only the secret value changes and the approved variable name remains the same.

Suspension or revocation is recorded as a new immutable event for the same digest. The latest event is authoritative. An expired, suspended, revoked, altered, or mismatched binding cannot execute.

The approval database is part of the canonical encrypted backup authority set.
